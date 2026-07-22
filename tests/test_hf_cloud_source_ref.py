from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "hf-cloud-core"


def test_docker_source_requires_branch_and_exact_commit_match() -> None:
    docker = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG ALPECCA_GIT_REF=main" in docker
    assert "ARG ALPECCA_GIT_SHA" in docker
    assert 'test -n "${ALPECCA_GIT_SHA}"' in docker
    assert 'git check-ref-format --branch "${ALPECCA_GIT_REF}"' in docker
    assert '--branch "${ALPECCA_GIT_REF}"' in docker
    assert 'rev-parse HEAD)" = "${ALPECCA_GIT_SHA}"' in docker
    assert "codex/voice-session-audio-normalization" not in docker


def test_space_metadata_and_public_port_remain_exact() -> None:
    readme = (DEPLOY / "README.md").read_text(encoding="utf-8")
    docker = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    metadata = readme.split("---", 2)[1]

    assert "sdk: docker" in metadata
    assert "app_port: 7860" in metadata
    assert "EXPOSE 7860\n" in docker
    assert "EXPOSE 7860 7861" not in docker


def test_documented_publication_gate_orders_source_before_space_rebuild() -> None:
    readme = (DEPLOY / "README.md").read_text(encoding="utf-8")
    gate = readme[readme.index("### Source publication gate"):]

    assert gate.index("Keep the Space paused") < gate.index(
        "Commit the complete GitHub runtime source first"
    )
    assert gate.index("Push the selected branch to `origin`") < gate.index(
        "set `ALPECCA_GIT_REF`"
    )
    assert gate.index("set `ALPECCA_GIT_SHA`") < gate.index(
        "Publish the contents of `deploy/hf-cloud-core/`"
    )
    assert gate.index("Publish the contents of `deploy/hf-cloud-core/`") < gate.index(
        "Resume or rebuild the Space"
    )
    assert "There is no local cloud-core deployment script" in gate
    assert "Variables** (not Secrets)" in gate
