from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_TS = ROOT / "apps" / "house-hq" / "src" / "main.ts"
SOURCE = MAIN_TS.read_text(encoding="utf-8")


def source_between(start: str, end: str) -> str:
    start_index = SOURCE.index(start)
    end_index = SOURCE.index(end, start_index)
    return SOURCE[start_index:end_index]


def test_main_uses_live_voice_input_with_barge_in_callback() -> None:
    assert 'from "./liveVoiceInput"' in SOURCE
    assert "const alpeccaLiveVoiceInput = new LiveVoiceInput({" in SOURCE

    setup = source_between(
        "const alpeccaLiveVoiceInput = new LiveVoiceInput({",
        "let chatWasPointerLocked",
    )
    assert "onSpeechStart:" in setup
    assert "alpeccaVoiceSession.interrupt(" in setup
    assert "onSegment: (wavBytes, metadata) => enqueueAlpeccaLiveVoiceSegment(wavBytes, metadata)" in setup


def test_push_to_talk_path_no_longer_uses_media_recorder() -> None:
    live_call = source_between(
        'type AlpeccaLiveVoiceUiState =',
        "async function closeAlpeccaCamera",
    )
    assert "MediaRecorder" not in live_call
    assert "ondataavailable" not in live_call
    assert "alpeccaLiveVoiceInput.start()" in live_call
    assert "alpeccaLiveVoiceInput.stop()" in live_call

    # MediaRecorder remains valid for the separate creator voice-enrollment flow.
    assert SOURCE.count("new MediaRecorder(") == 1
    enrollment_start = SOURCE.index("async function enrollAlpeccaCreatorVoice()")
    assert SOURCE.index("new MediaRecorder(") > enrollment_start


def test_microphone_button_starts_and_ends_a_live_call() -> None:
    assert 'id="alpeccaPushToTalk"' in SOURCE
    assert 'title="Start live voice call"' in SOURCE
    assert 'aria-label="Start live voice call"' in SOURCE

    ui_state = source_between(
        "function setAlpeccaLiveVoiceUiState(",
        "function handleAlpeccaLiveVoiceState(",
    )
    assert 'active ? "End live voice call" : "Start live voice call"' in ui_state
    assert 'alpeccaPushToTalkButton.setAttribute("aria-pressed", String(active))' in ui_state
    assert "alpeccaPushToTalkButton.disabled = false" in ui_state

    toggle = source_between(
        "async function toggleAlpeccaPushToTalk()",
        "async function closeAlpeccaCamera",
    )
    assert "await cancelAlpeccaPushToTalk();" in toggle
    assert "await alpeccaLiveVoiceInput.start();" in toggle


def test_microphone_turns_explicitly_request_voice_delivery() -> None:
    transcription = source_between(
        "async function transcribeAlpeccaLiveVoiceSegment(",
        "async function toggleAlpeccaPushToTalk()",
    )
    assert 'sendAlpeccaChat(heard, "", "microphone")' in transcription

    delivery_rule = 'delivery: privatePerception === "microphone" ? "voice" : "text"'
    assert SOURCE.count(delivery_rule) == 2


def test_raw_wav_is_sent_only_to_listen_with_capability_headers() -> None:
    transcription = source_between(
        "async function transcribeAlpeccaLiveVoiceSegment(",
        "async function toggleAlpeccaPushToTalk()",
    )
    assert 'new Blob([Uint8Array.from(wavBytes)], { type: "audio/wav" })' in transcription
    assert '`${alpeccaAiBaseUrl}/listen`' in transcription
    assert 'alpeccaCapabilityLeaseHeaders(lease, { "Content-Type": "audio/wav" })' in transcription
    assert "body: audio" in transcription
    assert 'acquireAlpeccaCapabilityLease("push_to_talk")' in transcription

    assert SOURCE.count("/listen") == 1
    assert SOURCE.count("Uint8Array.from(wavBytes)") == 1


def test_live_voice_work_is_fenced_to_the_current_session_and_speech_state() -> None:
    transcription = source_between(
        "async function transcribeAlpeccaLiveVoiceSegment(",
        "async function toggleAlpeccaPushToTalk()",
    )
    assert "generation !== alpeccaLiveVoiceGeneration" in transcription
    assert "speechGeneration === alpeccaLiveVoiceSpeechGeneration" in transcription
    assert "alpeccaLiveVoiceGeneration += 1" in SOURCE
    assert "alpeccaLiveVoiceSpeechGeneration += 1" in SOURCE


def test_voice_playback_uses_sentence_segmentation() -> None:
    assert "splitVoiceSpeechSegments," in SOURCE
    playback = source_between(
        "function playAlpeccaVoice(",
        "function startAlpeccaSpeech(",
    )
    assert "const segments = splitVoiceSpeechSegments(clean);" in playback
    assert "segments.map((segment) => alpeccaVoiceSession.enqueueSpeech({" in playback
    assert "prepareAlpeccaVoiceAudio(segment, preview, signal)" in playback


def test_playback_unlock_retries_after_browser_audio_context_suspension() -> None:
    unlock = source_between(
        "function unlockAlpeccaVoicePlayback()",
        "async function prepareAlpeccaVoiceAudio(",
    )
    assert "if (alpeccaVoicePlaybackUnlocked) return" not in unlock
    assert 'alpeccaVoiceAudioContext.state === "closed"' in unlock
    assert 'context.state !== "running"' in unlock
    assert "alpeccaVoiceAudioContext === context" in unlock


def test_mobile_backgrounding_stops_capture_playback_and_unlock_state() -> None:
    lifecycle = source_between(
        "function stopAlpeccaHouseVoiceForPageLifecycle(",
        'window.addEventListener("pagehide"',
    )
    assert "cancelAlpeccaPushToTalk()" in lifecycle
    assert "alpeccaVoiceSession.interrupt({ clearQueue: true, reason })" in lifecycle
    assert "alpeccaVoiceAudioContext = null" in lifecycle
    assert "alpeccaVoicePlaybackUnlocked = false" in lifecycle
    assert 'document.addEventListener("visibilitychange"' in lifecycle
    assert 'document.visibilityState === "hidden"' in lifecycle

    pagehide = SOURCE[SOURCE.index('window.addEventListener("pagehide"'):]
    assert "persistAlpeccaPose()" in pagehide
    assert 'stopAlpeccaHouseVoiceForPageLifecycle("House page hidden")' in pagehide
