"""Self-fencing uvicorn entrypoint for the promoted cloud CoreMind."""
from __future__ import annotations

from collections.abc import Callable, MutableMapping
import os


class CloudServerStartupError(RuntimeError):
    """The supervisor did not provide a complete inherited lease tuple."""


def _validated_port(environ: MutableMapping[str, str]) -> int:
    try:
        port = int(environ.get("ALPECCA_SERVER_PORT", environ.get("PORT", "7860")))
    except (TypeError, ValueError) as exc:
        raise CloudServerStartupError("cloud server port is invalid") from exc
    if not 1 <= port <= 65_535:
        raise CloudServerStartupError("cloud server port is invalid")
    return port


def _require_inherited_fence(environ: MutableMapping[str, str]) -> None:
    lease_id = str(environ.get("ALPECCA_CONTINUITY_LEASE_ID") or "").strip()
    holder = str(environ.get("ALPECCA_CONTINUITY_LEASE_HOLDER") or "").strip()
    try:
        epoch = int(str(
            environ.get("ALPECCA_CONTINUITY_FENCING_EPOCH") or ""
        ).strip())
    except (TypeError, ValueError) as exc:
        raise CloudServerStartupError("cloud continuity fence is incomplete") from exc
    if not (1 <= len(lease_id) <= 96 and 1 <= len(holder) <= 96 and epoch >= 1):
        raise CloudServerStartupError("cloud continuity fence is incomplete")
    if str(environ.get("ALPECCA_CONTINUITY_ROLE") or "") != "cloud-standby":
        raise CloudServerStartupError("cloud continuity role is invalid")


def main(
    *,
    environ: MutableMapping[str, str] | None = None,
    process_id: int | None = None,
    runner: Callable[..., object] | None = None,
) -> int:
    """Bind server.py's launcher-PID guard to this exact uvicorn process."""
    values = os.environ if environ is None else environ
    _require_inherited_fence(values)
    pid = os.getpid() if process_id is None else int(process_id)
    if pid < 1:
        raise CloudServerStartupError("cloud server process id is invalid")
    values["ALPECCA_CONTINUITY_LAUNCHER_PID"] = str(pid)
    port = _validated_port(values)
    if runner is None:
        import uvicorn

        runner = uvicorn.run
    runner(
        "server:app",
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
