"""Fit `color.py`'s season boundaries to real faces, through the live API.

`_WARM_REDNESS` (18.5) and `_DEEP_CONTRAST_L` (39.0) were fitted to eight
portraits measured from their own pixels by `measure_seasonal_colors.py`.
That is free and repeatable, but it is not quite what runs in production:
YouCam's `skin_color` is white-balance normalised and its `eyebrow_color`
read is its own, and the single live eyebrow sample we have (#59312e, a*
18) is redder than any of the eight. This script closes that gap by
measuring the same axes on YouCam's own scale.

It runs a folder of photos through the same crop -> upload -> poll path
`analyze_color` uses, records each returned skin/eyebrow/eye/hair hex with
the two axes the season rule thresholds, and -- if you label the photos --
reports the boundary that best separates the labelled groups.

    # what it costs: ~16 credits per photo. Check the balance first.
    python3 scripts/calibrate_undertone.py --credits

    # measure a folder; appends to calibration.csv so runs accumulate
    python3 scripts/calibrate_undertone.py photos/

    # only some of them (credits are finite -- see --credits)
    python3 scripts/calibrate_undertone.py photos/ --only spring.png winter_2.png

    # labels come from the filename ("summer_2.png" -> summer -> cool);
    # a CSV of "filename,season" overrides that where they disagree
    python3 scripts/calibrate_undertone.py photos/ --labels labels.csv

WHAT TO SHOOT: 6-10 different people, ideally a spread of undertones you
are confident about, each a front-on photo of the same kind the kiosk
takes. Same-person variants (different hair, different grading) do NOT add
calibration signal -- the skin hex barely moves, which is exactly what the
six samples we already have proved.

The suggested boundary is only as good as the labels: it is the midpoint
of the widest gap between the two groups, and it prints the overlap when
they aren't separable on that axis -- which is a real possible outcome,
and worth knowing before trusting the axis. It is what ruled out skin hue.
"""

import argparse
import asyncio
import csv
import logging
import math
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cv.measure import extract_landmarks  # noqa: E402
from app.youcam.client import YouCamClient  # noqa: E402
from app.youcam.color import (  # noqa: E402
    _crop_face,
    _encode_jpeg,
    _is_pose_rejection,
    _lab_from_hex,
    _level_eyes,
    _run_analysis,
    _symmetrise_face,
    _upscale_for_upload,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
WARM_SEASONS = {"spring", "autumn", "fall"}
COOL_SEASONS = {"summer", "winter"}
DEEP_SEASONS = {"autumn", "winter"}
LIGHT_SEASONS = {"spring", "summer"}


def _axes(colors: dict) -> dict:
    """The two numbers `_season_from_colors` thresholds, plus skin hue.

    Skin hue is still recorded, and only recorded: it was the old undertone
    signal and separated nothing on the eight labelled portraits, so it is
    here as evidence rather than as an axis to fit.
    """
    skin = _lab_from_hex(colors.get("skin_color"))
    brow = _lab_from_hex(colors.get("eyebrow_color"))
    eye = _lab_from_hex(colors.get("eye_color"))
    if skin is None:
        return {"redness": None, "contrast": None, "hue": None, "skin_L": None}
    dark = [feature[0] for feature in (brow, eye) if feature is not None]
    return {
        "redness": round(skin[1] + brow[1], 1) if brow is not None else None,
        "contrast": round(skin[0] - sum(dark) / len(dark), 1) if dark else None,
        "hue": round(math.degrees(math.atan2(skin[2], skin[1])), 1),
        "skin_L": round(skin[0], 1),
    }


def _prepare(bgr):
    """The image to upload, plus a note on how it was obtained.

    A calibration folder holds whatever you could find: full-body shots,
    head-and-shoulders, and faces already cropped tight. The body-crop path
    needs shoulders to size the head box, so on an already-cropped face it
    either can't see them or produces a degenerate box -- in that case the
    picture IS the crop, and we upload it as it is. Eye-levelling still
    applies wherever landmarks exist, since roll is the one pose problem a
    rotation can remove.
    """
    try:
        landmarks = extract_landmarks(bgr)
    except ValueError:
        return _upscale_for_upload(bgr), "whole image (no landmarks)"
    try:
        return _upscale_for_upload(_crop_face(bgr, landmarks=landmarks)), "cropped"
    except ValueError:
        levelled, _ = _level_eyes(bgr, landmarks)
        return _upscale_for_upload(levelled), "whole image (levelled)"


async def _measure(path: Path) -> dict:
    """One photo -> its YouCam colours, or an error string. ~16 credits,
    doubled if the pose is rejected and the symmetrised retry is needed."""
    bgr = cv2.imread(str(path))
    if bgr is None:
        return {"file": path.name, "error": "unreadable"}

    image, how = _prepare(bgr)
    face_bytes = _encode_jpeg(image)
    if face_bytes is None:
        return {"file": path.name, "error": "could not encode"}

    calls = 1
    try:
        async with YouCamClient() as api:
            try:
                result = await _run_analysis(api, face_bytes)
            except Exception as e:  # noqa: BLE001 -- reported per photo, never fatal
                if not _is_pose_rejection(e):
                    return {"file": path.name, "how": how, "calls": calls,
                            "error": str(e).split("failed: ")[-1]}
                calls += 1
                result = await _run_analysis(api, _encode_jpeg(_symmetrise_face(image)))
                how += " + symmetrised retry"
    except Exception as e:  # noqa: BLE001
        return {"file": path.name, "how": how, "calls": calls,
                "error": str(e).split("failed: ")[-1]}

    colors = (result.get("results") or {}).get("color") or {}
    return {
        "file": path.name,
        "how": how,
        "calls": calls,
        "skin": colors.get("skin_color"),
        "eyebrow": colors.get("eyebrow_color"),
        "eye": colors.get("eye_color"),
        "hair": colors.get("hair_color"),
        "hair_name": colors.get("hair_color_name"),
        **_axes(colors),
    }


def _label_of(raw: str):
    """A season name (or the bare word) -> its half on each axis."""
    raw = raw.strip().lower()
    if raw in WARM_SEASONS or raw in COOL_SEASONS:
        return {"undertone": "warm" if raw in WARM_SEASONS else "cool",
                "depth": "deep" if raw in DEEP_SEASONS else "light"}
    if raw in {"warm", "cool"}:
        return {"undertone": raw, "depth": None}
    if raw in {"deep", "light"}:
        return {"undertone": None, "depth": raw}
    return None


def _label_from_filename(name: str):
    """"summer_2.png" -> cool + light. The season is the leading word of the
    name; a trailing _2 marks a second sample of the same season."""
    return _label_of(Path(name).stem.split("_")[0])


def _load_labels(path: Path) -> dict:
    """filename -> labels, from a season name or a bare warm/cool/deep/light."""
    labels = {}
    with path.open() as fh:
        for row in csv.reader(fh):
            if len(row) < 2:
                continue
            label = _label_of(row[1])
            if label:
                labels[row[0].strip()] = label
    return labels


def _suggest_boundary(rows, labels, *, axis, key, high, low, constant):
    """Report where `constant` should sit to split the labelled groups."""
    def group(which):
        return sorted(r[axis] for r in rows
                      if r.get(axis) is not None
                      and (labels.get(r["file"]) or {}).get(key) == which)

    hi, lo = group(high), group(low)
    print(f"\n{high}-labelled {axis}: {hi}")
    print(f"{low}-labelled {axis}: {lo}")
    if not hi or not lo:
        print(f"  no suggestion: need at least one {high}- and one {low}-labelled face "
              f"with a usable {axis}.")
        return
    if min(hi) > max(lo):
        print(f"  cleanly separable. Suggested {constant} = {(min(hi) + max(lo)) / 2:.1f}"
              f"  (margin {min(hi) - max(lo):.1f})")
        return
    overlap = sorted([v for v in lo if v >= min(hi)] + [v for v in hi if v <= max(lo)])
    print(f"  OVERLAP at {overlap} -- {axis} does not separate these faces, so no single"
          f"\n  threshold fits. Either the labels disagree with the API's read, or this axis"
          f"\n  needs a second signal rather than a better number.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", help="folder of front-on photos, one face each")
    ap.add_argument("--labels", help="CSV of filename,season (or filename,warm|cool); "
                                     "defaults to reading the season from each filename")
    ap.add_argument("--only", nargs="+", metavar="NAME",
                    help="measure just these filenames, to control what you spend")
    ap.add_argument("--out", default="calibration.csv", help="results CSV, appended to")
    ap.add_argument("--credits", action="store_true", help="print the credit balance and exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    if args.credits:
        async def show():
            async with YouCamClient() as api:
                resp = await api._client.get("/s2s/v1.0/client/credit", headers=api._headers())
                total = sum(r["amount"] for r in resp.json()["results"])
                print(f"{total} credits (~{total // 16} photos at ~16 each)")
        asyncio.run(show())
        return

    if not args.folder:
        ap.error("give a folder of photos, or --credits")

    photos = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if args.only:
        wanted = set(args.only)
        photos = [p for p in photos if p.name in wanted]
        missing = wanted - {p.name for p in photos}
        if missing:
            sys.exit(f"not in {args.folder}: {', '.join(sorted(missing))}")
    if not photos:
        sys.exit(f"no images in {args.folder}")
    print(f"{len(photos)} photos -> about {len(photos) * 16} credits, more if poses are "
          f"rejected. Ctrl-C now to stop.\n")

    # Filename first ("summer_2.png" -> cool), overridden by an explicit CSV.
    labels = {p.name: _label_from_filename(p.name) for p in photos}
    labels = {k: v for k, v in labels.items() if v}
    if args.labels:
        labels.update(_load_labels(Path(args.labels)))
    unlabelled = [p.name for p in photos if p.name not in labels]
    if unlabelled:
        print(f"no season in the name of: {', '.join(unlabelled)} (measured, but not fitted)\n")

    rows = [asyncio.run(_measure(p)) for p in photos]

    def _season(name):
        return Path(name).stem.split("_")[0] if name in labels else "-"

    header = ("file", "label", "skin", "eyebrow", "redness", "contrast", "hue", "hair")
    print("\n" + f"{header[0]:16s} {header[1]:7s} {header[2]:9s} {header[3]:9s} "
                 f"{header[4]:>7s} {header[5]:>8s} {header[6]:>6s} {header[7]:10s} how")
    for r in rows:
        if r.get("error"):
            print(f"{r['file']:16s} {_season(r['file']):7s} FAILED: {r['error']} "
                  f"[{r.get('how', '')}]")
            continue

        def _num(value):
            return "     -" if value is None else f"{value:6.1f}"

        print(f"{r['file']:16s} {_season(r['file']):7s} {str(r['skin']):9s} "
              f"{str(r['eyebrow']):9s} {_num(r['redness']):>7s} {_num(r['contrast']):>8s} "
              f"{_num(r['hue']):>6s} {str(r.get('hair_name')):10s} {r['how']}")

    spent = sum(r.get("calls", 0) for r in rows) * 16
    print(f"\n~{spent} credits spent ({sum(r.get('calls', 0) for r in rows)} calls)")

    fields = ["file", "skin", "eyebrow", "eye", "hair", "hair_name",
              "redness", "contrast", "hue", "skin_L", "undertone", "depth"]
    measured = [r for r in rows if r.get("skin_L") is not None]
    out = Path(args.out)
    with out.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if out.stat().st_size == 0:
            writer.writeheader()
        for r in measured:
            label = labels.get(r["file"]) or {}
            writer.writerow({**{k: r.get(k) for k in fields if k in r},
                             "undertone": label.get("undertone") or "",
                             "depth": label.get("depth") or ""})
    print(f"\nappended {len(measured)} rows to {out}")

    if not labels:
        print("\nLabel the photos (--labels, or name them by season) for a boundary suggestion.")
        return
    _suggest_boundary(measured, labels, axis="redness", key="undertone",
                      high="warm", low="cool", constant="_WARM_REDNESS")
    _suggest_boundary(measured, labels, axis="contrast", key="depth",
                      high="deep", low="light", constant="_DEEP_CONTRAST_L")
    _suggest_boundary(measured, labels, axis="hue", key="undertone",
                      high="warm", low="cool", constant="(skin hue -- recorded, not used)")


if __name__ == "__main__":
    main()
