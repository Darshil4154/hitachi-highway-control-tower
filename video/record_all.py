#!/usr/bin/env python3
"""Record every chapter clip for the Hack the Highway demo rebuild."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "video"))

from lib import protect
from lib.harness import CLIPS, OUT, Tour, launch
from lib.numbers import load
from lib.slides import render_slide_clip

SHOTLIST: list[dict] = []
N = load()


def run(cmd: list[str], **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def ffmpeg_still_from_webm(webm: Path, mp4: Path, min_s: float = 3.0) -> None:
    """Convert Playwright webm to mp4; pad if short."""
    mp4.parent.mkdir(parents=True, exist_ok=True)
    # probe duration
    probe = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(webm)])
    dur = float(probe.stdout.strip() or "0")
    args = ["ffmpeg", "-y", "-i", str(webm)]
    if dur < min_s:
        args += ["-vf", f"tpad=stop_mode=clone:stop_duration={min_s - dur}"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-an", str(mp4)]
    run(args)


def finish_page_recording(context, page, dest: Path) -> None:
    """Close page to flush Playwright video, then convert."""
    video = page.video
    page.close()
    raw = Path(video.path()) if video else None
    context.close()
    if not raw or not raw.exists():
        raise RuntimeError(f"no video for {dest}")
    ffmpeg_still_from_webm(raw, dest)
    raw.unlink(missing_ok=True)


def chapter_slide(num: str, name: str, title: str, subtitle: str = "", footnote: str = "") -> Path:
    stem = f"{num}_{name}"
    print(f"== slide {stem}")
    return render_slide_clip(stem, title, subtitle, footnote, seconds=4.0)


def chapter_terminal() -> Path:
    """03: official dry-run summary + self-check + pytest, rendered as a terminal clip."""
    print("== 03 official run")
    dest = CLIPS / "03_official_run.mp4"
    work = OUT / "_terminal"
    work.mkdir(parents=True, exist_ok=True)
    # Capture real command outputs (dry-run is fast with cache; do not write scored log)
    dry = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-m", "control_tower.run", "--dry-run", "--events", "E-05"],
        cwd=ROOT, capture_output=True, text=True,
    )
    sc = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "eval/self_check.py", "--log", "runs/final_v2/action_log.jsonl"],
        cwd=ROOT, capture_output=True, text=True,
    )
    pt = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-m", "pytest", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    lines = [
        "$ python -m control_tower.run --dry-run --events E-05",
        *(dry.stdout.splitlines()[-12:] or dry.stderr.splitlines()[-12:]),
        "",
        f"$ python eval/self_check.py --log runs/final_v2/action_log.jsonl",
        *(sc.stdout.splitlines()[-20:]),
        "",
        "$ pytest -q",
        *(pt.stdout.splitlines()[-8:]),
        "",
        f"RESULT  events {N['self_check_pass']}/{N['events']} green   writes {N['writes']}   failed {N['failed']}   tests {N['tests']} passed",
        f"model {N['model']}   reads {N['reads']}   LLM calls {N['llm_calls']}",
    ]
    script = work / "terminal.txt"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Render scrolling terminal with ffmpeg drawtext is painful; use matplotlib frames
    import matplotlib.pyplot as plt
    frames = []
    shown = []
    for i, line in enumerate(lines):
        shown.append(line)
        fig = plt.figure(figsize=(19.2, 9.6), dpi=100, facecolor="#0b1220")
        ax = fig.add_axes([0.04, 0.06, 0.92, 0.88])
        ax.set_facecolor("#0b1220")
        ax.axis("off")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        text = "\n".join(shown[-28:])
        ax.text(0.0, 1.0, text, color="#e2e8f0", fontsize=14, family="monospace",
                va="top", ha="left", wrap=False)
        ax.text(0.0, 0.02, "4x", color="#f59e0b", fontsize=20, fontweight="bold")
        fp = work / f"f{i:03d}.png"
        fig.savefig(fp, facecolor=fig.get_facecolor())
        plt.close(fig)
        frames.append(fp)
    # 3-4x: ~0.18s per line
    list_path = work / "list.txt"
    with list_path.open("w", encoding="utf-8") as f:
        for fp in frames:
            f.write(f"file '{fp}'\n")
            f.write("duration 0.18\n")
        f.write(f"file '{frames[-1]}'\n")
        f.write("duration 2.5\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
         "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         str(dest)])
    return dest


def with_recording(stem: str):
    """Start a Playwright context that records into a temp dir."""
    tmp = OUT / "_rec" / stem
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    return launch(tmp), tmp


def chapter_ops_overview() -> Path:
    print("== 04 event ops overview")
    dest = CLIPS / "04_event_ops_overview.mp4"
    (pw, browser, context, page), tmp = with_recording("04")
    t = Tour(page, SHOTLIST)
    t.chapter = "04_event_ops_overview"
    t.t0 = time.time()
    t.inject()
    # KPI strip
    body = page.inner_text("body")
    for label, val in (("EVENTS", str(N["events"])), ("WRITE ACTIONS", str(N["writes"])),
                       ("FAILED CALLS", str(N["failed"]))):
        if str(val) not in body and val not in body:
            # Streamlit may format differently
            pass
    # Highlight KPI-ish text
    for text in (str(N["events"]), str(N["incidents"]), str(N["escalations"]),
                 str(N["noise"]), str(N["writes"]), "0"):
        loc = page.get_by_text(text, exact=True)
        if loc.count():
            t.highlight(loc.first)
            t.keep_alive(1.2)
    # Annotation overlay via evaluate
    page.evaluate(f"""() => {{
      const d=document.createElement('div');
      d.id='__ct_anno';
      d.style.cssText='position:fixed;right:24px;top:120px;z-index:99999;background:#0f172acc;color:#fff;padding:14px 16px;border-radius:10px;font:600 16px sans-serif;max-width:360px;';
      d.innerHTML = '{N["events"]} events = {N["actionable_events"]} actionable + {N["escalated_events"]} escalated + {N["noise_events"]} noise<br/>{N["incidents"]} incidents (E-01 is compound: 2 incidents)';
      document.body.appendChild(d);
    }}""")
    t.keep_alive(3.5)
    # Point at model
    m = page.get_by_text(N["model"].split(":")[0], exact=False)
    if m.count():
        t.highlight(m.first)
        t.keep_alive(1.5)
    # Replay run
    replay = page.get_by_role("button", name="▶ Replay run")
    if replay.count() == 0:
        replay = page.get_by_text("Replay run")
    t.click(replay.first, "Replay run")
    # Replay sleeps 15s in app - wait through it
    time.sleep(min(16, N["events"] + 2))
    t.wait_idle(60)
    t.keep_alive(2)
    browser_ctx = context
    finish_page_recording(browser_ctx, page, dest)
    browser.close()
    pw.stop()
    return dest


def chapter_event(stem: str, eid: str, filt: str | None, actions) -> Path:
    print(f"== {stem}")
    dest = CLIPS / f"{stem}.mp4"
    (pw, browser, context, page), tmp = with_recording(stem)
    t = Tour(page, SHOTLIST)
    t.chapter = stem
    t.t0 = time.time()
    t.inject()
    t.nav("Event operations")
    if filt:
        pill = page.get_by_text(filt, exact=True)
        if pill.count():
            t.click(pill.first, f"filter {filt}")
    t.open_event(eid)
    actions(t, page)
    finish_page_recording(context, page, dest)
    browser.close()
    pw.stop()
    return dest


def e09_actions(t: Tour, page) -> None:
    # message / extraction
    for phrase in ("Orbit", "surround-view", "Huntsville", "Extraction"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first)
            t.keep_alive(1.4)
    # excluded expander
    excl = page.get_by_text("Excluded on purpose", exact=False)
    if excl.count():
        t.click(excl.first, "open excluded rule 10")
        t.keep_alive(2)
    # schedule tab
    tab = page.get_by_text("Schedule before / after", exact=True)
    if tab.count():
        t.click(tab.first, "schedule tab")
        t.keep_alive(1)
        page.mouse.wheel(0, 700)
        t.keep_alive(2.5)
        page.mouse.wheel(0, 500)
        t.keep_alive(2)
    # action log
    al = page.get_by_text("Action log", exact=True)
    if al.count():
        t.click(al.first, "action log")
        t.keep_alive(1)
        for rule in ("R1", "R3", "R5"):
            loc = page.get_by_text(rule, exact=False)
            if loc.count():
                t.highlight(loc.first)
                t.keep_alive(1.2)
    # verifier
    vf = page.get_by_text("Verifier", exact=True)
    if vf.count():
        t.click(vf.first, "verifier")
        t.keep_alive(1)
        page.mouse.wheel(0, 400)
        for word in ("plan", "world", "ok", "PASS", "green"):
            loc = page.get_by_text(word, exact=False)
            if loc.count():
                t.highlight(loc.first)
                t.keep_alive(1.0)
                break
        t.keep_alive(2)


def e01_actions(t: Tour, page) -> None:
    for phrase in ("next Friday", "San Antonio", "Princeton", "Compound"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first)
            t.keep_alive(1.3)
    # sub-incident buttons
    for label in ("plant outage", "supplier delay", "E-01-I1", "E-01-I2", "E-01-i1", "E-01-i2"):
        loc = page.get_by_text(label, exact=False)
        if loc.count():
            t.click(loc.first, f"subincident {label}")
            t.keep_alive(1.5)
            break
    # sidebar NEXT_WEEKDAY
    side = page.locator('[data-testid="stSidebar"]')
    sw = side.get_by_text("NEXT_WEEKDAY", exact=False)
    if sw.count():
        t.highlight(sw.first)
        t.keep_alive(2.5)
    # action log notify
    al = page.get_by_text("Action log", exact=True)
    if al.count():
        t.click(al.first, "action log")
        loc = page.get_by_text("dealer.notify", exact=False)
        if loc.count():
            t.highlight(loc.first)
            t.keep_alive(2)


def e03_actions(t: Tour, page) -> None:
    for phrase in ("LOT-", "unsold", "owners", "stop"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first)
            t.keep_alive(1.2)
    al = page.get_by_text("Action log", exact=True)
    if al.count():
        t.click(al.first, "action log")
        for tool in ("quality.hold_lot", "dealer.stop_sale", "crm.notify_customer"):
            loc = page.get_by_text(tool, exact=False)
            if loc.count():
                t.highlight(loc.first)
                t.keep_alive(1.3)


def e05_actions(t: Tour, page) -> None:
    for phrase in ("Ignored", "rule 7", "not operational"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first)
            t.keep_alive(1.8)
    al = page.get_by_text("Action log", exact=True)
    if al.count():
        t.click(al.first, "empty action log")
        t.keep_alive(2)


def guardrail_actions(t: Tour, page) -> None:
    # E-09 already has guardrail often - open E-01 or E-09
    for phrase in ("Guardrail", "grounding", "not used"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first)
            try:
                t.click(loc.first, "expand guardrail")
            except Exception:
                pass
            t.keep_alive(3)
            break


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    before = protect.snapshot()
    (OUT / "numbers.json").write_text(json.dumps(N, indent=2), encoding="utf-8")

    chapter_slide("00", "title", "Hack the Highway",
                  "Wacky Wheels Control Tower",
                  "The LLM reads, code decides.")
    chapter_slide("01", "problem", "The problem",
                  "Just-in-time builds. Messy messages. Real operational risk.")
    chapter_slide("02", "architecture", "Architecture",
                  "Small local LLM classifies. Deterministic agents decide.")

    chapter_terminal()
    try:
        chapter_ops_overview()
    except Exception as e:
        print("WARN 04 failed:", e)

    try:
        chapter_event("05_e09_supplier_delay", "E-09", "delay", e09_actions)
    except Exception as e:
        print("WARN 05 failed:", e)
    try:
        chapter_event("06_e01_compound", "E-01", "compound", e01_actions)
    except Exception as e:
        print("WARN 06 failed:", e)
    try:
        chapter_event("07_e03_quality", "E-03", "quality", e03_actions)
    except Exception as e:
        print("WARN 07 failed:", e)
    try:
        chapter_event("08_e05_noise", "E-05", "noise", e05_actions)
    except Exception as e:
        print("WARN 08 failed:", e)
    try:
        chapter_event("09_guardrail", "E-09", "delay", guardrail_actions)
    except Exception as e:
        print("WARN 09 failed:", e)

    # Remaining chapters in a second script for clarity
    from record_rest import record_rest
    record_rest(SHOTLIST, N)

    protect.restore(before)

    # shotlist
    with (OUT / "shotlist.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["chapter", "t", "action", "element", "number", "source"])
        w.writeheader()
        for row in SHOTLIST:
            w.writerow(row)
    print("clips:", sorted(p.name for p in CLIPS.glob("*.mp4")))


if __name__ == "__main__":
    main()
