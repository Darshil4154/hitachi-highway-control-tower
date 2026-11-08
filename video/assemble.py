#!/usr/bin/env python3
"""Assemble chapter clips into clean + captioned deliverables."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "video" / "out"
CLIPS = OUT / "clips"

ORDER = [
    "00_title", "01_problem", "02_architecture", "03_official_run",
    "04_event_ops_overview", "05_e09_supplier_delay", "06_e01_compound",
    "07_e03_quality", "08_e05_noise", "09_guardrail", "10_hitl_e02",
    "11_knowledge_graph", "12_ask", "13_live_desk", "14_whatif",
    "15_policy_studio", "16_audit", "17_ops_health", "18_daily_briefing",
    "19_results", "20_close",
]

SHORT = ["00_title", "03_official_run", "04_event_ops_overview", "05_e09_supplier_delay",
         "06_e01_compound", "10_hitl_e02", "14_whatif", "15_policy_studio", "19_results"]


def run(cmd):
    subprocess.run(cmd, check=True)


def probe(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True)
    return float(out.strip())


def concat(names: list[str], dest: Path) -> list[tuple[str, float, float]]:
    """Return chapter timeline (name, start, end)."""
    lst = OUT / "_concat.txt"
    timeline = []
    t = 0.0
    lines = []
    for name in names:
        p = CLIPS / f"{name}.mp4"
        if not p.exists():
            print("MISSING clip", p)
            continue
        d = probe(p)
        # normalize to 1920x960 yuv420p
        norm = OUT / f"_norm_{name}.mp4"
        run(["ffmpeg", "-y", "-i", str(p),
             "-vf", "scale=1920:960:force_original_aspect_ratio=decrease,pad=1920:960:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(norm)])
        lines.append(f"file '{norm}'")
        timeline.append((name, t, t + probe(norm)))
        t = timeline[-1][2]
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dest)])
    return timeline


def load_captions() -> list[dict]:
    # captions keyed by chapter prefix; filled from captions_source.json
    src = OUT / "captions_source.json"
    return json.loads(src.read_text(encoding="utf-8"))


def write_srt(timeline: list[tuple[str, float, float]], captions: list[dict], path: Path) -> None:
    def ts(s: float) -> str:
        h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")

    # Map chapter -> caption lines with relative times inside chapter
    by_ch: dict[str, list] = {}
    for c in captions:
        by_ch.setdefault(c["chapter"], []).append(c)

    cues = []
    n = 1
    for name, start, end in timeline:
        for c in by_ch.get(name, []):
            a = start + float(c["start"])
            b = start + float(c["end"])
            b = min(b, end - 0.05)
            if b <= a:
                continue
            text = c["text"]
            if "—" in text or "–" in text or "—" in text:
                raise SystemExit(f"em/en dash in caption: {text}")
            cues.append(f"{n}\n{ts(a)} --> {ts(b)}\n{text}\n")
            n += 1
    path.write_text("\n".join(cues), encoding="utf-8")


def caption_band(clean: Path, srt: Path, dest: Path) -> None:
    """Pad 120px dark band and burn subtitles into that band only via margin."""
    # App is 1920x960; output 1920x1080 with black pad at bottom; force_style MarginV keeps text in band
    run([
        "ffmpeg", "-y", "-i", str(clean),
        "-vf", (
            "pad=1920:1080:0:0:black,"
            f"subtitles={srt}:force_style="
            "'FontName=DejaVu Sans,FontSize=38,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "BackColour=&H80000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=28,Alignment=2'"
        ),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-an",
        str(dest),
    ])


def chapters_txt(timeline: list[tuple[str, float, float]], path: Path) -> None:
    labels = {
        "00_title": "Title", "01_problem": "Problem", "02_architecture": "Architecture",
        "03_official_run": "Official run", "04_event_ops_overview": "Event operations",
        "05_e09_supplier_delay": "E-09 supplier delay", "06_e01_compound": "E-01 compound",
        "07_e03_quality": "E-03 quality hold", "08_e05_noise": "E-05 noise",
        "09_guardrail": "Guardrail", "10_hitl_e02": "Human review",
        "11_knowledge_graph": "Knowledge graph", "12_ask": "Ask the control tower",
        "13_live_desk": "Live Incident Desk", "14_whatif": "Scenario Lab and What-if",
        "15_policy_studio": "Policy Studio", "16_audit": "Audit trail",
        "17_ops_health": "Operations health", "18_daily_briefing": "Daily briefing",
        "19_results": "Results", "20_close": "Close",
    }
    lines = []
    for name, start, _ in timeline:
        m, s = divmod(int(start), 60)
        h, m = divmod(m, 60)
        stamp = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        lines.append(f"{stamp} {labels.get(name, name)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clean = OUT / "demo_full_clean.mp4"
    timeline = concat(ORDER, clean)
    (OUT / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    chapters_txt(timeline, OUT / "chapters.txt")

    captions = load_captions()
    srt = OUT / "captions.srt"
    write_srt(timeline, captions, srt)

    captioned = OUT / "demo_full_captioned.mp4"
    caption_band(clean, srt, captioned)

    short = OUT / "demo_short_cut.mp4"
    concat(SHORT, short)

    print("wrote", clean, "duration", probe(clean))
    print("wrote", captioned, "duration", probe(captioned))
    print("wrote", short, "duration", probe(short))


if __name__ == "__main__":
    main()
