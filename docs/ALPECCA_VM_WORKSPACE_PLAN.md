# Alpecca VM Workspace — Planning & Foundation (Delegation Lane P)

**Authored:** 2026-07-13 (Claude Code session). **Scope gate:** planning + creator-run checklist
**only**. Per `docs/CLAUDE_FABLE_PARALLEL_DELEGATION.md` Lane P, no VMware install, guest creation,
screen stream, or "hands" agent is built until **(a)** the Phase 9 computer-use security gate
passes and **(b)** the engine choice is explicitly approved. The engine is now approved (below);
**live control remains BLOCKED** until the P9 gate.

This is the canonical VM-workspace document. It supersedes the VM sections scattered in
`.claude/plans/flickering-meandering-seal.md` and `docs/ALPECCA_UNIFIED_MASTER_PLAN.md` for
foundation detail.

## Purpose
Give Alpecca a dedicated, **isolated** virtual desktop — her body's workspace — where she runs
creative apps (Clip Studio, VRoid, Blender), Discord, Google Drive, files, and games via her
computer-use system, while her **mind (server.py + Ollama + memory + Mindscape) stays on the
host**. Isolation is the point: a VM crash is a *workspace outage, not death*. The VM never
becomes a second CoreMind, and cloud/VM loss is never a reason to clone or silently reroute her.

## Decisions (approved by Jason)
| Axis | Choice | Why |
|---|---|---|
| Engine | **VMware Workstation Pro (free personal)** | Only pragmatic GPU-capable path on a single RTX 3050 4 GB *laptop* GPU: VirtualBox has no real 3D; Easy-GPU-PV/Hyper-V GPU-PV is "laptop NVIDIA not supported"; VFIO needs a Linux host + collapses on muxless Optimus. Recorded tradeoff: **not open-source**. |
| Guest OS | **Windows 11** | Clip Studio Paint + VRoid Studio are Windows-only. |
| Drive | **Dedicated second (spinning) HDD** | Isolation on its own disk. Usable with tuning; an SSD is the top future upgrade. |
| Host | **This Dell G15 laptop** | Shares ~24 GB RAM + 4 GB VRAM with her brain — the core constraint. |

## Resource budget (host vs guest)
Host total: **~24 GB DDR4**, **RTX 3050 Laptop 4 GB VRAM**, shared.

| Resource | Host + brain reserve | Guest allocation | Rule |
|---|---|---|---|
| RAM | ≥ 16 GB | **6–8 GB** | Never starve the host; guest sized so `qwen3.5:9b` still loads on host. |
| VRAM (4 GB) | brain's Ollama models | VMware 3D shares the same 4 GB | **Contention is real:** heavy guest 3D (Blender render, games) and local inference can't run flat-out together. Sequence them, or route the brain to cloud (ZeroGPU/Colab) during heavy creative sessions. |
| vCPU | leave ≥ 2 host cores | **4 vCPU** | — |
| Disk | — | fixed-size VMDK filling most of the HDD | Fixed beats dynamic on a spinning disk (less fragmentation). |

## Storage plan (dedicate the HDD)
- Format the second HDD NTFS; it holds **only** her VM.
- Use a **fixed-size (pre-allocated) VMDK**, single file on NTFS, sized to most of the drive.
- Prefer VMDK-on-drive over raw physical-disk mapping — simpler, safer, snapshot-friendly.
- Keep her large art assets on a **shared folder**, not inside the VMDK, to keep the image lean.
- Guest HDD tuning: disable SysMain/Superfetch, Windows Search indexing, visual effects, and
  hibernation; small fixed pagefile.

## Network design (private brain↔hands channel)
- **Host-only adapter (vmnet1)** — the private link the host brain uses to command the future
  guest "hands" agent and receive its frame stream. Not routable off-box.
- **NAT adapter** — her internet (Discord, Google Drive, browser).
- Isolation invariant: only the **host brain** may reach the guest agent's control port; the
  guest holds **no secrets** and receives only high-level intents.

## Snapshot & kill-switch strategy
- **Clean-baseline snapshot** immediately after apps install → she can always revert.
- Periodic **work snapshots** before risky operations (driver installs, big app updates).
- **Kill switch:** the host can hard-stop the VM at any time (VMware power-off / process kill).
  Because her mind is on the host, a kill is a workspace outage only. A future host-side control
  will expose a one-click "stop her workspace" that also revokes the `vm_control` lease.

## Threat model (what isolation buys, what stays gated)
- **On the host (never in the guest):** CoreMind, Ollama + models, memory/Mindpage/Mindscape,
  creator secrets, capability-lease authority. The guest never authenticates as creator.
- **In the guest:** only her workspace apps + (future) a hands agent with no secrets, reachable
  only over host-only net.
- **Attack surface to keep closed:** the guest is treated as *untrusted* toward the host —
  no host drive auto-mount beyond a scoped shared folder, no clipboard exfil of secrets, no
  guest-initiated calls to host services other than the audited hands-agent channel.
- **Still BLOCKED until the P9 computer-use gate passes** (delegation Lane P): the guest hands
  agent, the "watch Alpecca work" stream, live computer control, and any `vm_control` lease.
  Building those before P9 is out of scope.

## Failure tests (to run once the VM exists)
1. **Isolation / "not death":** hard-kill the running guest → host CoreMind keeps serving on
   :8765, Ollama unaffected, no memory corruption. VM restart returns to workspace.
2. **Resource starvation:** guest at 6–8 GB RAM while host loads `qwen3.5:9b` → no host OOM,
   host stays responsive.
3. **VRAM contention:** start a Blender viewport render in-guest while the brain answers a turn →
   observe/measure degradation; confirm the documented "sequence, don't overlap" rule.
4. **Network isolation:** confirm only the host-only adapter reaches the (future) control port;
   NAT gives internet but not host-service access.
5. **Snapshot restore:** corrupt/dirty the guest, revert to clean baseline, confirm bit-clean.

## Creator-run install checklist (Jason performs; I cannot install/accept EULAs/enter keys)
1. Download **VMware Workstation Pro (free)** from Broadcom (free account), **≥ 17.6** for
   Hyper-V/WSL2 coexistence if Docker/WSL2 is in use.
2. Format the second HDD (NTFS), dedicate it to the VM.
3. Create the Windows 11 guest with the settings in *Resource budget* + *Storage plan*
   (UEFI + Secure Boot + virtual TPM; 4 vCPU; 6–8 GB RAM; fixed VMDK; 3D accel ON, 2–3 GB gfx
   mem; host-only + NAT adapters).
4. Install Windows 11 (your ISO + license). Consider **Win 11 IoT Enterprise LTSC** / debloated
   for a lean HDD appliance.
5. Apply guest HDD tuning (above); install **VMware Tools** (3D, shared folders, clipboard).
6. Install her apps: Clip Studio Paint, VRoid Studio, Blender, Discord, Google Drive, a browser.
   (Art stays real-tools/shapes-and-lines — never gen-AI; her art never goes to Cloudflare.)
7. Take the **clean-baseline snapshot**.
8. Tell me when it's up — I'll run the failure tests and, once the **P9 gate** passes, build the
   host-side VM target + guest hands agent + watch-page under a new `vm_control` capability lease.

## Deferred to the post-P9 integration (not this lane)
- Guest-side "hands" agent (UI-Automation via `uiautomation`/`pywinauto` + SoM/OCR fallback).
- Host-side `"vm"` target evolving `computer.py` into a skill registry; new `vm_control` lease
  policy mirroring `screen_share` in `alpecca/capability_leases.py`; creator-gate on
  `/computer/task`.
- The outbound "watch Alpecca work" stream page.
- Per-app skills: Blender, Clip Studio, VRoid, Google Drive, files, games.

## Cross-references
- Delegation authority: `docs/CLAUDE_FABLE_PARALLEL_DELEGATION.md` (Lane P).
- Experience overlay: `docs/ALPECCA_UNIFIED_MASTER_PLAN.md` (Track E).
- Spine + safety: `docs/ALPECCA_MASTER_PLAN.md` (Phase 9 computer-use gate).
