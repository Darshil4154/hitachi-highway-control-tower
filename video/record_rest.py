"""Chapters 10-20: HITL, graph, ask, desk, what-if, policy, audit, health, briefing, slides."""
from __future__ import annotations

import time
from pathlib import Path

from lib.harness import CLIPS, Tour, finish_page_recording, with_recording
from lib.slides import render_slide_clip


def record_rest(shotlist: list, N: dict) -> None:
    # 10 HITL
    try:
        _hitl(shotlist)
    except Exception as e:
        print("WARN 10 failed:", e)
    # 11 KG
    try:
        _kg(shotlist, N)
    except Exception as e:
        print("WARN 11 failed:", e)
    # 12 Ask
    try:
        _ask(shotlist)
    except Exception as e:
        print("WARN 12 failed:", e)
    # 13 Desk
    try:
        _desk(shotlist)
    except Exception as e:
        print("WARN 13 failed:", e)
    # 14 What-if + Scenario Lab
    try:
        _whatif(shotlist)
    except Exception as e:
        print("WARN 14 failed:", e)
    # 15 Policy
    try:
        _policy(shotlist)
    except Exception as e:
        print("WARN 15 failed:", e)
    # 16 Audit
    try:
        _audit(shotlist)
    except Exception as e:
        print("WARN 16 failed:", e)
    # 17 Health
    try:
        _health(shotlist)
    except Exception as e:
        print("WARN 17 failed:", e)
    # 18 Briefing
    try:
        _briefing(shotlist)
    except Exception as e:
        print("WARN 18 failed:", e)

    render_slide_clip(
        "19_results",
        "Results",
        f"{N['self_check_pass']}/{N['events']} green  |  {N['writes']} writes  |  {N['failed']} failed  |  {N['tests']} tests",
        f"model {N['model']}  |  reads {N['reads']}  |  nodes {N['nodes']:,}",
        seconds=5.0,
    )
    render_slide_clip(
        "20_close",
        "Thank you",
        "cursor.com/codebase/pragathii-arumugam-udhayakumar/highway-tower",
        "Hack the Highway - Wacky Wheels Control Tower",
        seconds=4.0,
    )


def _hitl(shotlist: list) -> None:
    print("== 10 hitl")
    dest = CLIPS / "10_hitl_e02.mp4"
    (pw, browser, context, page), _ = with_recording("10")
    t = Tour(page, shotlist); t.chapter = "10_hitl_e02"; t.t0 = time.time(); t.inject()
    t.nav("Event operations")
    page.get_by_text("escalated", exact=True).first.click(); t.wait_idle()
    t.open_event("E-02")
    for phrase in ("Escalated", "rule 8", "Missing"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first); t.keep_alive(1.5)
    t.nav("Human review inbox")
    note = page.get_by_placeholder("e.g. asked supplier rep for details")
    if note.count():
        t.click(note.first)
        note.first.fill("asked supplier rep for details")
        t.keep_alive(1)
    approve = page.locator(".st-key-approved-E-02 button")
    if approve.count() == 0:
        approve = page.get_by_role("button", name="Approve")
    t.click(approve.first, "Approve E-02")
    t.keep_alive(2.5)
    # caption: enterprise server never called
    page.evaluate("""() => {
      const d=document.createElement('div');
      d.style.cssText='position:fixed;left:24px;bottom:24px;z-index:99999;background:#0f172acc;color:#fff;padding:10px 14px;border-radius:8px;font:600 15px sans-serif';
      d.textContent='HITL is local only - the enterprise server is never called from here.';
      document.body.appendChild(d);
    }""")
    t.keep_alive(2.5)
    finish_page_recording(context, page, dest); browser.close(); pw.stop()


def _kg(shotlist: list, N: dict) -> None:
    print("== 11 knowledge graph")
    dest = CLIPS / "11_knowledge_graph.mp4"
    (pw, browser, context, page), _ = with_recording("11")
    t = Tour(page, shotlist); t.chapter = "11_knowledge_graph"; t.t0 = time.time(); t.inject()
    t.nav("Knowledge graph")
    t.keep_alive(2)
    for text in (f"{N['nodes']:,}", str(N["nodes"]), "Nodes", "Edges", str(N["edges"])):
        loc = page.get_by_text(text, exact=False)
        if loc.count():
            t.highlight(loc.first); t.keep_alive(1.4)
    page.mouse.wheel(0, 500); t.keep_alive(2)
    finish_page_recording(context, page, dest); browser.close(); pw.stop()


def _ask(shotlist: list) -> None:
    print("== 12 ask")
    dest = CLIPS / "12_ask.mp4"
    (pw, browser, context, page), _ = with_recording("12")
    t = Tour(page, shotlist); t.chapter = "12_ask"; t.t0 = time.time(); t.inject()
    t.nav("Ask the control tower")
    box = page.get_by_placeholder("", exact=False)
    # chat input
    chat = page.locator('[data-testid="stChatInput"] textarea')
    if chat.count() == 0:
        chat = page.locator("textarea")
    q = "Which Platinum customers are affected by E-09?"
    t.click(chat.first)
    chat.first.fill(q)
    chat.first.press("Enter")
    # wait for answer
    for _ in range(60):
        if "Platinum" in page.inner_text("body") or "function" in page.inner_text("body").lower():
            break
        time.sleep(1)
    t.keep_alive(2)
    page.mouse.wheel(0, 400); t.keep_alive(3)
    finish_page_recording(context, page, dest); browser.close(); pw.stop()


def _desk(shotlist: list) -> None:
    print("== 13 live desk")
    dest = CLIPS / "13_live_desk.mp4"
    (pw, browser, context, page), _ = with_recording("13")
    t = Tour(page, shotlist); t.chapter = "13_live_desk"; t.t0 = time.time(); t.inject()
    t.nav("Live Incident Desk")
    area = page.locator("textarea")
    msg = ("Supplier update: Orbit cameras for Huntsville slip again. "
           "Original Friday Mar 26 now Tuesday Mar 30. Confirmed by the carrier.")
    t.click(area.first)
    area.first.fill(msg)
    t.keep_alive(1)
    btn = page.get_by_role("button", name="Run in the twin")
    t.click(btn.first, "run twin")
    for _ in range(90):
        body = page.inner_text("body")
        if "simulation" in body.lower() or "plan" in body.lower() or "verifier" in body.lower():
            break
        time.sleep(1)
    for phrase in ("simulation", "nothing sent", "twin", "Verifier"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first); t.keep_alive(1.5)
    page.mouse.wheel(0, 600); t.keep_alive(2)
    finish_page_recording(context, page, dest); browser.close(); pw.stop()


def _whatif(shotlist: list) -> None:
    print("== 14 what-if")
    dest = CLIPS / "14_whatif.mp4"
    (pw, browser, context, page), _ = with_recording("14")
    t = Tour(page, shotlist); t.chapter = "14_whatif"; t.t0 = time.time(); t.inject()
    # Scenario Lab briefly
    t.nav("Scenario Lab")
    t.keep_alive(2)
    run = page.get_by_role("button", name="Run scenario")
    if run.count():
        t.highlight(run.first); t.keep_alive(1.5)

    t.nav("What-if")
    # Scenario A defaults plant outage P_NC
    t.click(page.get_by_role("button", name="Run A"), "run A")
    for _ in range(40):
        if "Affected orders" in page.inner_text("body") or "units" in page.inner_text("body").lower():
            break
        time.sleep(0.5)
    t.keep_alive(2)
    # Scenario B: change end date or plant via selectboxes - pick Quality hold for difference
    # Change B kind to Quality hold
    # Streamlit selectboxes are tricky; try radio/select labeled Scenario type under B
    selects = page.locator('input[aria-label="Scenario type"]')
    if selects.count() >= 2:
        selects.nth(1).click()
        page.keyboard.type("Quality")
        page.keyboard.press("Enter")
        t.wait_idle()
    t.click(page.get_by_role("button", name="Run B"), "run B")
    for _ in range(40):
        time.sleep(0.5)
        if "Side by side" in page.inner_text("body"):
            break
    page.mouse.wheel(0, 900); t.keep_alive(2)
    for phrase in ("Units delayed", "Platinum", "Loaners", "Side by side", "simulation"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first); t.keep_alive(1.3)
    t.keep_alive(2)
    finish_page_recording(context, page, dest); browser.close(); pw.stop()


def _policy(shotlist: list) -> None:
    print("== 15 policy studio")
    dest = CLIPS / "15_policy_studio.mp4"
    (pw, browser, context, page), _ = with_recording("15")
    t = Tour(page, shotlist); t.chapter = "15_policy_studio"; t.t0 = time.time(); t.inject()
    t.nav("Policy Studio (manager)")
    for phrase in ("Scored baseline", "handbook_v1", "read-only", "baseline"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first); t.keep_alive(1.5)
    # Switches section - change TRANSFER_LOWER_BOUND in draft
    sec = page.get_by_text("Switches", exact=True)
    if sec.count():
        t.click(sec.first, "switches")
    # Preview
    prev = page.get_by_text("Preview impact", exact=True)
    if prev.count():
        t.click(prev.first, "preview section")
    btn = page.get_by_role("button", name="Preview impact on 15 events")
    if btn.count() == 0:
        btn = page.get_by_text("Preview impact", exact=False)
    if btn.count():
        t.click(btn.first, "run preview")
        for _ in range(120):
            body = page.inner_text("body")
            if "robustness" in body.lower() or "15/15" in body or "handbook" in body.lower():
                break
            time.sleep(1)
        t.keep_alive(2)
        page.mouse.wheel(0, 500); t.keep_alive(2)
    # Publish section
    pub = page.get_by_text("Publish", exact=True)
    if pub.count():
        t.click(pub.first, "publish section")
    # fill author/reason if inputs exist
    for label, val in (("Author", "Demo recorder"), ("Reason", "Demo publish for video - safe copy")):
        inp = page.get_by_label(label, exact=False)
        if inp.count():
            inp.first.fill(val)
    pub_btn = page.get_by_role("button", name="Publish")
    if pub_btn.count():
        # Only publish if there is a draft change - may no-op on baseline
        try:
            t.click(pub_btn.first, "publish")
            t.keep_alive(3)
        except Exception as e:
            print("publish skipped", e)
    # Note official run refuses
    page.evaluate("""() => {
      const d=document.createElement('div');
      d.style.cssText='position:fixed;left:24px;bottom:24px;z-index:99999;background:#0f172acc;color:#fff;padding:10px 14px;border-radius:8px;font:600 15px sans-serif;max-width:520px';
      d.textContent='Official run always loads handbook_v1 unless you pass --policy.';
      document.body.appendChild(d);
    }""")
    t.keep_alive(3)
    finish_page_recording(context, page, dest); browser.close(); pw.stop()


def _audit(shotlist: list) -> None:
    print("== 16 audit")
    dest = CLIPS / "16_audit.mp4"
    (pw, browser, context, page), _ = with_recording("16")
    t = Tour(page, shotlist); t.chapter = "16_audit"; t.t0 = time.time(); t.inject()
    t.nav("Audit trail")
    # Rule multiselect - open and pick R5
    rule = page.get_by_label("Rule", exact=False)
    if rule.count():
        t.click(rule.first)
        page.keyboard.type("R5")
        page.keyboard.press("Enter")
        t.wait_idle(); t.keep_alive(2)
    dealer = page.get_by_label("Dealer", exact=False)
    if dealer.count() == 0:
        # columns may use different labels
        pass
    else:
        t.click(dealer.first)
        page.keyboard.type("D")
        page.keyboard.press("Enter")
        t.wait_idle(); t.keep_alive(2)
    dl = page.get_by_text("Download CSV", exact=False)
    if dl.count():
        t.highlight(dl.first); t.keep_alive(2)
    page.mouse.wheel(0, 400); t.keep_alive(2)
    finish_page_recording(context, page, dest); browser.close(); pw.stop()


def _health(shotlist: list) -> None:
    print("== 17 health")
    dest = CLIPS / "17_ops_health.mp4"
    (pw, browser, context, page), _ = with_recording("17")
    t = Tour(page, shotlist); t.chapter = "17_ops_health"; t.t0 = time.time(); t.inject()
    t.nav("Operations health")
    for phrase in ("Failed calls", "Cache", "Extract", "Slowest", "Model"):
        loc = page.get_by_text(phrase, exact=False)
        if loc.count():
            t.highlight(loc.first); t.keep_alive(1.3)
    page.mouse.wheel(0, 500); t.keep_alive(2)
    page.mouse.wheel(0, 500); t.keep_alive(2)
    finish_page_recording(context, page, dest); browser.close(); pw.stop()


def _briefing(shotlist: list) -> None:
    print("== 18 briefing")
    dest = CLIPS / "18_daily_briefing.mp4"
    (pw, browser, context, page), _ = with_recording("18")
    t = Tour(page, shotlist); t.chapter = "18_daily_briefing"; t.t0 = time.time(); t.inject()
    t.nav("Daily briefing")
    page.mouse.wheel(0, 400); t.keep_alive(2)
    page.mouse.wheel(0, 500); t.keep_alive(2)
    pdf = page.get_by_text("Download one-page PDF", exact=False)
    if pdf.count():
        t.highlight(pdf.first); t.keep_alive(1.5)
        # trigger download
        with page.expect_download(timeout=15000) as dl:
            pdf.first.click()
        download = dl.value
        path = CLIPS / "daily_briefing.pdf"
        download.save_as(path)
        t.keep_alive(1)
        # show PDF pages as images appended by converting with pdftoppm if available
    # Show PDF via ffmpeg still if saved
    finish_page_recording(context, page, dest); browser.close(); pw.stop()
    pdf_path = CLIPS / "daily_briefing.pdf"
    if pdf_path.exists():
        # append 3s of PDF render
        try:
            import subprocess
            subprocess.run(["pdftoppm", "-png", "-r", "120", "-f", "1", "-l", "1",
                            str(pdf_path), str(CLIPS / "_brief_pdf")], check=False)
            png = CLIPS / "_brief_pdf-1.png"
            if not png.exists():
                png = next(CLIPS.glob("_brief_pdf*.png"), None)
            if png and png.exists():
                tmp = CLIPS / "_brief_pdf.mp4"
                subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-t", "3",
                                "-vf", "scale=1920:960:force_original_aspect_ratio=decrease,pad=1920:960:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(tmp)],
                               check=True, capture_output=True)
                # concat briefing + pdf
                lst = CLIPS / "_b18.txt"
                lst.write_text(f"file '{dest}'\nfile '{tmp}'\n", encoding="utf-8")
                out = CLIPS / "18_daily_briefing_full.mp4"
                subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                                "-c", "copy", str(out)], check=True, capture_output=True)
                out.replace(dest)
        except Exception as e:
            print("pdf preview skipped", e)
