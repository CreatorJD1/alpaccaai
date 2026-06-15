"""Ingest a batch of her real art: classify each image into Jason's scheme, then file it.

This is the one-command front door for a drop of her art (e.g. the 97 "Update2" images
that arrived from Drive with opaque hash names). It runs each image through HER local
vision model against HIS authoritative role taxonomy + canon-QC rules
(`alpecca/artlib.py`, lifted from the Claude Image Naming Guide) and places it where it
belongs -- reference sheet vs production bust vs Live2D layer candidate vs reject --
flagging anything that breaks canon (black shirt, floating ears, bad lanyard, grids).

The batch's own CSV manifest can't be name-joined to the files (the export renamed
everything to hashes), so her perception re-derives the classification instead.

Two passes, with a human gate in the middle (Jason reviews/corrects before any file
moves):

  1. CLASSIFY (default):
         python scripts/ingest_art.py data/incoming/update2/Update2
     Looks at every image, writes `<folder>/_ingest_proposed.json` with each image's
     role code, secondary tags, canon verdict, and a proposed canonical name in his
     grammar (alpecca_<code>_<nnn>_<descriptor>_v01.png). Moves nothing. Open that
     file, fix any mis-tags (especially anything flagged canon_ok=false).

  2. APPLY (renames the local source AND populates the app library):
         python scripts/ingest_art.py data/incoming/update2/Update2 --apply
     Reads the (edited) proposal and does both: (a) on the source side, preserves every
     raw file untouched in 00_raw_originals/ and drops a renamed copy (its canonical
     name) into the right guide folder by role -- 01_reference_sheets / 02_approved_
     character_busts / 03_wardrobe_modes / 04_motion_desktop_chibi / 05_live2d_layers /
     99_rejects_redo; (b) on the app side, copies production-ready assets into
     `data/avatar/library/` and merges `library.json` -- the set that drives her
     avatar. Canon-failures and reference-only roles are still organized on disk but
     held OUT of the app library; pass --include-flagged to library-file them too.

Grounding + graceful degradation, same contract as the rest of the senses: if the
vision model isn't pulled or Ollama is down, classification returns `unknown` for that
image (flagged for a human glance) rather than crashing or inventing a tag.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from alpecca import artlib
from alpecca import vision

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PROPOSAL_NAME = "_ingest_proposed.json"
LIBRARY_DIR = config.AVATAR_DIR / "library"
MANIFEST_NAME = "library.json"

# Roles that are reference-only or rejects per the guide -- still catalogued, but not
# treated as production assets unless the human explicitly opts them in.
NON_PRODUCTION = {"reject_composite", "misc", "legacy", "source_ref", artlib.UNKNOWN}


def _images(folder: Path) -> list[Path]:
    """Every image in the drop, sorted for stable indexing across re-runs. Skips the
    folders we create ourselves so a re-run doesn't re-ingest already-filed copies."""
    ours = {artlib.RAW_DIR, "01_reference_sheets", "02_approved_character_busts",
            "03_wardrobe_modes", "04_motion_desktop_chibi", "05_live2d_layers",
            artlib.REDO_DIR}
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS
                  and p.parent.name not in ours)


def _vlm_bytes(img: Path, max_side: int = 896) -> bytes:
    """The bytes we actually hand the vision model: the image downscaled so its long
    edge is `max_side`. These are ~1.7MB 1122x1402 PNGs and the model spends inference
    time proportional to pixels -- classification (role/expression) doesn't need full
    resolution, so this is a several-fold speedup with no real accuracy cost. Falls
    back to the raw bytes if Pillow isn't importable, so it never hard-fails."""
    try:
        import io
        from PIL import Image
        im = Image.open(img)
        im.thumbnail((max_side, max_side))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return img.read_bytes()


def classify(folder: Path) -> Path:
    """Pass 1: look at each image, write the reviewable proposal. The proposal is
    rewritten after every image, so progress is visible live and a crash mid-run keeps
    everything classified so far (re-runs are cheap to resume by hand). Returns its path."""
    imgs = _images(folder)
    proposal_path = folder / PROPOSAL_NAME
    if not imgs:
        print(f"No images ({', '.join(sorted(IMAGE_EXTS))}) found in {folder}")
        return proposal_path

    prompt = artlib.classification_prompt()
    per_cat = Counter()            # running per-category index, matching his grammar
    proposals, blank, flagged = [], 0, 0
    for i, img in enumerate(imgs):
        tags = artlib.parse_classification(
            vision.describe_image(_vlm_bytes(img), prompt=prompt))
        if tags is None:           # model unavailable or no JSON -- leave it blank
            tags = {"category": artlib.UNKNOWN, "descriptor": "image",
                    "expression": artlib.UNKNOWN, "wardrobe": artlib.UNKNOWN,
                    "mouth": artlib.UNKNOWN, "canon_ok": True, "canon_issue": "",
                    "desc": ""}
            blank += 1
        per_cat[tags["category"]] += 1
        entry = {"source": img.name,
                 "name": artlib.proposed_name(tags, per_cat[tags["category"]], img.suffix),
                 **tags}
        proposals.append(entry)
        mark = "" if tags["canon_ok"] else f"  !! canon: {tags['canon_issue']}"
        if not tags["canon_ok"]:
            flagged += 1
        print(f"  [{i+1:>3}/{len(imgs)}] {img.name[:28]}  ->  "
              f"{tags['category']}{mark}", flush=True)
        # Persist after every image: visible progress + crash resilience.
        proposal_path.write_text(json.dumps(proposals, indent=2, ensure_ascii=False),
                                 encoding="utf-8")

    print(f"\nWrote {len(proposals)} proposals -> {proposal_path}")
    print("By category: " + ", ".join(f"{c}={n}" for c, n in per_cat.most_common()))
    if flagged:
        print(f"  {flagged} flagged canon_ok=false -- review before filing.")
    if blank:
        print(f"  {blank} came back blank (vision model offline?). Marked "
              f"'{artlib.UNKNOWN}' -- pull {config.Vision.MODEL} and re-run, or tag by hand.")
    print("Review/correct the tags, then re-run with --apply.")
    return proposal_path


def apply(folder: Path, include_flagged: bool = False) -> Path:
    """Pass 2 (both targets): rename the local source into his guide's folder system
    AND copy production-ready assets into the app library.

    Source side, faithful to the PDF's section 2: every raw file is preserved
    (relocated untouched into 00_raw_originals/), and a renamed copy under its
    canonical name is sorted by role into 01_reference_sheets / 02_approved_character_
    busts / 03_wardrobe_modes / 04_motion_desktop_chibi / 05_live2d_layers / 99_rejects_
    redo. App side: assets that pass canon and aren't reference-only are also copied
    into data/avatar/library/ and merged into library.json -- the set that drives her
    avatar. `include_flagged` additionally library-files canon-failures/reference roles."""
    proposal_path = folder / PROPOSAL_NAME
    if not proposal_path.exists():
        print(f"No {PROPOSAL_NAME} in {folder} -- run the classify pass first.")
        return LIBRARY_DIR / MANIFEST_NAME
    proposals = json.loads(proposal_path.read_text(encoding="utf-8"))

    raw_dir = folder / artlib.RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = LIBRARY_DIR / MANIFEST_NAME
    manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists() else {})

    organized = libraried = missing = 0
    for entry in proposals:
        # Locate the raw file: still loose in the source root on first run, or already
        # relocated to 00_raw_originals/ on a re-run. Either way, end with it in raw/.
        raw = raw_dir / entry["source"]
        root_src = folder / entry["source"]
        if root_src.exists():
            shutil.move(str(root_src), str(raw))   # preserve raw, untouched name
        if not raw.exists():
            print(f"  skip (missing file): {entry['source']}")
            missing += 1
            continue

        # Source side: renamed copy into the right guide folder.
        dest_dir = folder / artlib.guide_folder(entry)
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw, dest_dir / entry["name"])
        organized += 1

        # App side: only clean, production-ready roles unless the human opts in.
        production = (entry.get("canon_ok", True)
                      and entry.get("category") not in NON_PRODUCTION)
        if production or include_flagged:
            shutil.copy2(raw, LIBRARY_DIR / entry["name"])
            manifest = artlib.merge_into_manifest(manifest, {
                "file": entry["name"],
                "category": entry.get("category", artlib.UNKNOWN),
                "expression": entry.get("expression", artlib.UNKNOWN),
                "wardrobe": entry.get("wardrobe", artlib.UNKNOWN),
                "mouth": entry.get("mouth", artlib.UNKNOWN),
                "canon_ok": entry.get("canon_ok", True),
                "canon_issue": entry.get("canon_issue", ""),
                "desc": entry.get("desc", ""),
                "source": entry["source"],
            })
            libraried += 1

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print(f"Organized {organized} renamed file(s) into {folder} (raw preserved in "
          f"{artlib.RAW_DIR}/); {missing} missing.")
    print(f"Library now holds {libraried} production asset(s); manifest has "
          f"{len(manifest)} -> {manifest_path}")
    if not include_flagged:
        print("  (canon-failures + reference-only roles were organized into their "
              "folders but kept OUT of the app library; --include-flagged to add them.)")
    return manifest_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Classify and file a drop of her art.")
    ap.add_argument("folder", type=Path, help="folder of her exported images")
    ap.add_argument("--apply", action="store_true",
                    help="rename the source into his guide folders + fill the app library")
    ap.add_argument("--include-flagged", action="store_true",
                    help="also library-file canon-failing and reference-only images")
    args = ap.parse_args()

    folder = args.folder
    if not folder.is_dir():
        print(f"Not a folder: {folder}")
        sys.exit(2)

    if args.apply:
        apply(folder, include_flagged=args.include_flagged)
    else:
        classify(folder)


if __name__ == "__main__":
    main()
