"""Talk mode: speak with Alpecca out loud (Phase 4, tier 2 -- experimental).

A Pipecat pipeline that listens on your default microphone, transcribes
locally with Whisper, runs each utterance through Alpecca's full chat loop
(mood, memory, introspection -- via the same `/channel/inbound` endpoint the
OpenClaw bridge uses), and speaks her reply through local Kokoro TTS.
Everything runs on this machine; no audio or text leaves it.

This is a *separate process* from the Alpecca server, the same pattern as
run_telemetry.py: her mind stays in one place (server.py) and this script is
just another sense-and-actuator pair plugged into it over HTTP.

Setup (one-time):
    pip install "pipecat-ai[whisper,silero,local]" kokoro-onnx requests
    python server.py          # Alpecca herself must be running
    python scripts/run_talk.py

First run downloads the Whisper + Kokoro models; after that it's fully
offline. Ctrl+C to stop.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make the project root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import HOST, PORT

ALPECCA_URL = f"http://{HOST}:{PORT}"

# Pipecat and friends are optional, heavyweight deps -- guard the import and
# explain exactly what to install instead of stack-tracing at the user.
try:
    import requests
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineWorker
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.services.kokoro.tts import KokoroTTSService
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )
    from pipecat.workers.runner import WorkerRunner
except ImportError as exc:
    print("Talk mode needs Pipecat and its local-audio extras. Install with:\n")
    print('    pip install "pipecat-ai[whisper,silero,local]" kokoro-onnx requests\n')
    print(f"(missing: {exc.name})")
    sys.exit(2)


class AlpeccaTurn(FrameProcessor):
    """Bridges a finished transcription into Alpecca's chat loop.

    On each TranscriptionFrame we POST the text to `/channel/inbound` (channel
    "voice"), which runs the full sense->mood->memory->reply cycle inside the
    server, then push her reply downstream as a TTSSpeakFrame for Kokoro to
    voice. The HTTP hop is what keeps her mind single-instance: talk mode sees
    the same Alpecca, with the same mood and memories, as the browser chat.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            print(f"  you: {frame.text}")
            reply = await asyncio.get_running_loop().run_in_executor(
                None, self._ask_alpecca, frame.text
            )
            if reply:
                print(f"  alpecca: {reply}")
                await self.push_frame(TTSSpeakFrame(reply))
            return  # the transcription itself doesn't need to travel further

        await self.push_frame(frame, direction)

    @staticmethod
    def _ask_alpecca(text: str) -> str:
        try:
            resp = requests.post(
                f"{ALPECCA_URL}/channel/inbound",
                json={"text": text, "channel": "voice", "sender": "voice"},
                timeout=120,   # a slow local LLM is normal; don't give up early
            )
            resp.raise_for_status()
            return (resp.json().get("reply") or "").strip()
        except Exception as exc:
            print(f"  [couldn't reach Alpecca at {ALPECCA_URL}: {exc}]")
            return ""


async def main() -> None:
    # Make sure Alpecca is actually awake before we open the mic.
    try:
        requests.get(f"{ALPECCA_URL}/state", timeout=5).raise_for_status()
    except Exception:
        print(f"Alpecca isn't reachable at {ALPECCA_URL} -- start `python server.py` first.")
        sys.exit(1)

    transport = LocalAudioTransport(
        LocalAudioTransportParams(audio_in_enabled=True, audio_out_enabled=True)
    )

    pipeline = Pipeline([
        transport.input(),
        VADProcessor(vad_analyzer=SileroVADAnalyzer()),
        WhisperSTTService(),
        AlpeccaTurn(),
        KokoroTTSService(),
        transport.output(),
    ])

    print("Talk mode: listening. Say something to Alpecca. Ctrl+C to stop.")
    worker = PipelineWorker(pipeline)
    runner = WorkerRunner(handle_sigint=False if sys.platform == "win32" else True)
    await runner.add_workers(worker)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
