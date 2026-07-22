import asyncio
import builtins
import inspect
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "apps" / "vcs" / "backend" / "test_restyle.py"


def test_restyle_module_import_is_inert(monkeypatch):
    source = SCRIPT.read_text(encoding="utf-8")
    code = compile(source, str(SCRIPT), "exec")
    real_import = builtins.__import__

    def fail_io(*args, **kwargs):
        raise AssertionError("test_restyle performed file I/O during import")

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.partition(".")[0] in {"ai_service", "dotenv", "PIL"}:
            raise AssertionError(f"test_restyle imported {name} during collection")
        return real_import(name, globals, locals, fromlist, level)

    def fail_asyncio_run(*args, **kwargs):
        raise AssertionError("test_restyle started its workflow during import")

    namespace = {
        "__file__": str(SCRIPT),
        "__name__": "test_restyle_collection_probe",
    }

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", fail_io)
        guard.setattr(builtins, "__import__", guarded_import)
        guard.setattr(Path, "open", fail_io)
        guard.setattr(Path, "read_bytes", fail_io)
        guard.setattr(Path, "read_text", fail_io)
        guard.setattr(Path, "write_bytes", fail_io)
        guard.setattr(Path, "write_text", fail_io)
        guard.setattr(asyncio, "run", fail_asyncio_run)
        exec(code, namespace)

    assert inspect.iscoroutinefunction(namespace["main"])
    assert namespace["atlas_path"] == "texture_refs/original_outfit_atlas.png"
