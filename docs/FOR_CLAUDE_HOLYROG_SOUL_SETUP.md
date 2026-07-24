# Jason_HOLYROG Soul Research Setup

Updated: 2026-07-23

This is the machine-side work order for the separate Claude session on
`Jason_HOLYROG`. Do not paste worker secrets, model tokens, TLS private keys,
or dataset credentials into chat or Git.

## Architecture now in source

- One shared HyFusER-style text/speech projection and cross-modal fusion
  backbone.
- Seven distinct lightweight `TransformerEncoder` heads in Soul order:
  Feeler, Expressor, Carer, Doer, Wanderer, Reflector, Improver.
- The deterministic Soul remains authoritative. Transformer output is
  advisory, logged, and shadow-only.
- Emotion-LLaMA is an optional research teacher/evaluator, not Alpecca's chat
  model and not an authority over emotional state or actions.

## Sync and verify

```powershell
cd C:\Users\Jason\Documents\GitHub\alpaccaai
git fetch origin
git switch codex/research-integration-stages
git pull --ff-only
python -m pytest -q tests\test_rog_soul_transformer_model.py tests\test_multimodal_affect_fusion.py tests\test_rog_worker_server.py tests\test_rog_worker_client.py tests\test_emotion_llama_teacher.py
```

Confirm `python -c "import torch; print(torch.cuda.is_available())"` succeeds on
the ROG. Do not install Torch into the primary laptop runtime solely for this
feature.

## External research storage

Keep all of the following outside this repository, preferably under a dedicated
ROG data drive:

- Emotion-LLaMA source checkout.
- Llama-2/Emotion-LLaMA checkpoints.
- MER dataset files and extracted HuBERT/EVA/MAE/VideoMAE features.
- Seven-head training checkpoints and evaluation manifests.

The Emotion-LLaMA repository code is BSD-3-Clause. MER data remains governed by
its research EULA. CreatorJD accepted research use; that does not permit
redistribution or committing data to Git.

## Emotion-LLaMA qualification

Start from
`deploy/rog-emotion-llama/qualification.manifest.json`. Replace only the
external absolute paths and SHA-256 values after the files exist. Keep opt-in
disabled until every dependency and digest is verified, then run:

```powershell
python scripts\qualify_emotion_llama_teacher.py --manifest D:\AlpeccaResearch\emotion-llama\qualification.manifest.json
```

A failed or incomplete report is expected to fail closed. Do not modify the
adapter to treat source presence as model readiness.

## Seven-head worker activation

The worker reads these protected machine settings:

- `ALPECCA_ROG_HYFUSER_MODE=shadow-only`
- `ALPECCA_ROG_HYFUSER_WEIGHTS` as an absolute checkpoint path
- `ALPECCA_ROG_HYFUSER_WEIGHTS_SHA256` as the exact checkpoint digest
- `ALPECCA_ROG_HYFUSER_EVALUATION_MANIFEST` as the exact evaluation manifest

Restart only the ROG compute worker after configuring them. Do not start
CoreMind, Discord, memory writers, tunnels, or a second continuity lease on the
ROG.

Run the worker checks and verify its authenticated health endpoint reports the
canonical emotion order:

`neutral, joy, sadness, fear, anger, surprise, disgust`.

It must also report one shared backbone, seven ordered perspective heads,
`shadow_only=true`, `speaking=false`, and `state_mutation=false`.

## Promotion gate

Do not let transformer scores affect Soul urgency or focus until a held-out
evaluation manifest passes the source-enforced accuracy, calibration, coverage,
and sample-count thresholds. Promotion still requires a reviewed source change;
the checkpoint cannot self-declare qualification or authorize an action.
