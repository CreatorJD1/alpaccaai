---
title: Alpecca Cloud Desktop
emoji: "🖥️"
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
fullWidth: true
header: mini
---

# Alpecca Cloud Desktop

This is Alpecca's private, phone-accessible Ubuntu desktop surface. It is a
desktop-only continuity component: it does not contain, start, restore, or
claim leadership for CoreMind. The local laptop remains the only speaking
Alpecca until the repository's fenced P13 takeover gate is complete and
CreatorJD explicitly activates it.

The container runs as Linux UID 1000, exposes only noVNC on port 7860, and keeps
VNC itself on loopback. The Hugging Face Space must remain **private**. Runtime
state belongs under `/data/alpecca-desktop`; attach a private Hugging Face
Storage Bucket there before treating files as persistent. Without that volume,
the desktop survives only for the current Space runtime.

This image intentionally has no runtime package-manager executor. New apps are
added through the reviewed, CreatorJD-approved catalog and a new image build,
not through an unrestricted root shell.

## Local validation

```powershell
python -m pytest -q tests\test_hf_cloud_desktop.py
```

The published Space is private account infrastructure, not an always-awake
backup mind. Free CPU Spaces may sleep and restart; visiting the Space wakes the
desktop, while an attached bucket preserves its approved workspace files.
