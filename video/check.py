#!/usr/bin/env python3
"""make video-check: static-frame, dashes, numbers, hashes, clip presence."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.numbers import HANDBOOK, RUN_LOG, load, sha256

OUT = Path(__file__).resolve().parent / "out"
CLIPS = OUT / "clips"
REQUIRED = [
    "00_title", "01_problem", "02_architecture", "03_official_run",
    "04_event_ops_overview", "05_e09_supplier_delay", "06_e01_compound",
    "07_e03_quality", "08_e05_noise", "09_guardrail", "10_hitl_e02",
    "11_knowledge_graph", "12_ask", "13_live_desk", "14_whatif",
    "15_policy_studio", "16_audit", "17_ops_health", "18_daily_briefing",
    "19_results", "20_close",
]


def frame_diff_static(path: Path, max_static: float = 5.0) -> list[str]:
    """Warn if consecutive near-identical frames last > max_static seconds."""
    # Sample 2 fps and compare mae; cheap check
    work = OUT / "_check_frames"
    work.mkdir(parents=True, exist_ok=True)
    for p in work.glob("*.png"):
        p.unlink()
    subprocess.run([
        "ffmpeg", "-y", "-i", str(path), "-vf", "fps=2", str(work / "f%05d.png"),
    ], check=True, capture_output=True)
    frames = sorted(work.glob("f*.png"))
    issues = []
    if len(frames) < 3:
        return ["too few frames"]
    # compare file sizes as a crude static detector + optional pixel
    run = 1
    prev = frames[0].stat().st_size
    for i, f in enumerate(frames[1:], start=1):
        sz = f.stat().st_size
        if abs(sz - prev) < 200:  # nearly identical compressed size
            run += 1
        else:
            if run / 2.0 > max_static:
                issues.append(f"static ~{run/2:.1f}s near frame {i - run}")
            run = 1
        prev = sz
    if run / 2.0 > max_static:
        issues.append(f"static ~{run/2:.1f}s at end")
    return issues


def main() -> int:
    N = load()
    nums = OUT / "numbers.json"
    if nums.exists():
        saved = json.loads(nums.read_text(encoding="utf-8"))
        for k in ("events", "writes", "failed", "incidents", "tests", "nodes"):
            if saved.get(k) != N.get(k):
                print(f"FAIL number drift {k}: saved {saved.get(k)} now {N.get(k)}")
                return 1
    print("numbers OK", {k: N[k] for k in ("events", "writes", "failed", "tests", "nodes")})

    # hashes
    hb, al = sha256(HANDBOOK), sha256(RUN_LOG)
    print("handbook", hb[:16], "action_log", al[:16])
    if nums.exists():
        if saved.get("handbook_sha") != hb or saved.get("action_log_sha") != al:
            print("FAIL scored hash changed vs numbers.json snapshot")
            return 1
    print("scored-run hash: PASS")

    missing = [n for n in REQUIRED if not (CLIPS / f"{n}.mp4").exists()]
    if missing:
        print("FAIL missing clips:", missing)
        return 1
    empty = [n for n in REQUIRED if (CLIPS / f"{n}.mp4").stat().st_size < 1000]
    if empty:
        print("FAIL empty clips:", empty)
        return 1
    print("clips: PASS", len(REQUIRED))

    for name in ("captions.srt", "VOICEOVER_SCRIPT.md", "demo_full_clean.mp4", "demo_full_captioned.mp4"):
        # VOICEOVER is in video/
        pass
    srt = OUT / "captions.srt"
    script = Path(__file__).resolve().parent / "VOICEOVER_SCRIPT.md"
    for path in (srt, script):
        if not path.exists():
            print("FAIL missing", path)
            return 1
        text = path.read_text(encoding="utf-8")
        if "—" in text or "–" in text:
            print("FAIL em/en dash in", path)
            return 1
    print("dashes: PASS")

    # captions numbers must appear in numbers.json values
    srt_text = srt.read_text(encoding="utf-8")
    for key, val in (("writes", N["writes"]), ("events", N["events"]), ("failed", N["failed"]),
                     ("tests", N["tests"]), ("incidents", N["incidents"])):
        if str(val) not in srt_text:
            print(f"WARN caption may omit {key}={val}")
    print("caption numbers: checked")

    clean = OUT / "demo_full_clean.mp4"
    if clean.exists():
        issues = frame_diff_static(clean)
        if issues:
            print("WARN static segments:", issues[:8])
        else:
            print("static-frame: PASS")
    print("video-check done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
