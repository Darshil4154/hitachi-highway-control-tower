"""Playwright helpers: visible cursor, accent highlight, Streamlit waits."""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

URL = "http://127.0.0.1:8517"
CHROME = "/usr/local/bin/google-chrome"
OUT = Path(__file__).resolve().parents[1] / "out"
CLIPS = OUT / "clips"

CURSOR_JS = r"""
(() => {
  if (window.__ctCursor) return;
  const c = document.createElement('div');
  c.id = '__ct_cursor';
  c.style.cssText = 'position:fixed;z-index:2147483647;width:18px;height:18px;border-radius:50%;background:#ef4444;border:2px solid #fff;box-shadow:0 0 0 3px rgba(239,68,68,.35);pointer-events:none;transform:translate(-50%,-50%);left:40px;top:40px;transition:left .12s linear, top .12s linear;';
  const rip = document.createElement('div');
  rip.id = '__ct_rip';
  rip.style.cssText = 'position:fixed;z-index:2147483646;width:10px;height:10px;border-radius:50%;border:2px solid #ef4444;pointer-events:none;opacity:0;transform:translate(-50%,-50%);';
  document.documentElement.appendChild(c);
  document.documentElement.appendChild(rip);
  window.__ctCursor = {
    move(x,y){ c.style.left=x+'px'; c.style.top=y+'px'; },
    click(x,y){
      c.style.left=x+'px'; c.style.top=y+'px';
      rip.style.left=x+'px'; rip.style.top=y+'px'; rip.style.opacity='1';
      rip.style.width='10px'; rip.style.height='10px';
      rip.animate([{width:'10px',height:'10px',opacity:1},{width:'42px',height:'42px',opacity:0}],{duration:320,easing:'ease-out'});
      setTimeout(()=>{rip.style.opacity='0';},340);
    },
    clearHighlight(){
      document.querySelectorAll('.__ct_hl').forEach(el=>{
        el.classList.remove('__ct_hl');
        el.style.outline=''; el.style.boxShadow=''; el.style.borderRadius='';
      });
    },
    highlight(el){
      this.clearHighlight();
      if(!el) return;
      el.classList.add('__ct_hl');
      el.style.outline='3px solid #f59e0b';
      el.style.boxShadow='0 0 0 6px rgba(245,158,11,.25)';
      el.style.borderRadius='6px';
      el.scrollIntoView({behavior:'smooth', block:'center'});
    }
  };
})();
"""


class Tour:
    def __init__(self, page: Page, shotlist: list):
        self.page = page
        self.shotlist = shotlist
        self.chapter = ""
        self.t0 = time.time()

    def inject(self) -> None:
        self.page.evaluate(CURSOR_JS)

    def wait_idle(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            busy = self.page.locator('[data-testid="stStatusWidget"]')
            if busy.count() == 0 or not busy.first.is_visible():
                # also no running spinner text
                if self.page.locator("text=Running").count() == 0:
                    return
            time.sleep(0.2)

    def move_to(self, locator) -> None:
        self.inject()
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if not box:
            return
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.page.evaluate(f"window.__ctCursor && window.__ctCursor.move({x},{y})")
        self.page.mouse.move(x, y)
        time.sleep(0.25)

    def highlight(self, locator) -> None:
        self.inject()
        locator.scroll_into_view_if_needed()
        handle = locator.element_handle()
        if handle:
            self.page.evaluate("el => window.__ctCursor && window.__ctCursor.highlight(el)", handle)
        self.move_to(locator)
        time.sleep(0.6)

    def clear_hl(self) -> None:
        self.page.evaluate("window.__ctCursor && window.__ctCursor.clearHighlight()")

    def click(self, locator, note: str = "") -> None:
        self.highlight(locator)
        box = locator.bounding_box()
        if box:
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            self.page.evaluate(f"window.__ctCursor && window.__ctCursor.click({x},{y})")
        locator.click(force=True)
        self.wait_idle()
        time.sleep(0.4)
        if note:
            self.log(note)

    def log(self, action: str, element: str = "", number: str = "", source: str = "") -> None:
        self.shotlist.append({
            "chapter": self.chapter,
            "t": round(time.time() - self.t0, 2),
            "action": action,
            "element": element,
            "number": number,
            "source": source,
        })

    def nav(self, label: str) -> None:
        side = self.page.locator('[data-testid="stSidebar"]')
        self.click(side.get_by_text(label, exact=True).first, f"nav {label}")

    def open_event(self, eid: str) -> None:
        # Streamlit button key open-{eid}
        btn = self.page.locator(f".st-key-open-{eid} button")
        if btn.count() == 0:
            # filter first if needed
            btn = self.page.get_by_role("button", name="Open")
        self.click(btn.first if btn.count() else self.page.get_by_text(eid, exact=True).first, f"open {eid}")
        # assert selected
        body = self.page.inner_text("body")
        if f"selected: {eid}" not in body and eid not in body:
            raise AssertionError(f"failed to open {eid}")
        self.log(f"opened {eid}", eid)

    def keep_alive(self, seconds: float = 2.0) -> None:
        """No static stretch: nudge the cursor."""
        end = time.time() + seconds
        while time.time() < end:
            self.page.evaluate("window.__ctCursor && window.__ctCursor.move(Math.random()*400+200, Math.random()*200+120)")
            time.sleep(0.8)


def launch(record_dir: Path | None = None):
    """Context manager-ish: returns (playwright, browser, context, page)."""
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=CHROME,
        headless=False,
        args=["--no-sandbox", f"--window-size=1920,1080", "--window-position=0,0",
              "--force-device-scale-factor=1.25"],
    )
    kwargs: dict = {
        "viewport": {"width": 1920, "height": 960},
        "device_scale_factor": 1.25,
        "record_har_path": None,
    }
    if record_dir:
        record_dir.mkdir(parents=True, exist_ok=True)
        kwargs["record_video_dir"] = str(record_dir)
        kwargs["record_video_size"] = {"width": 1920, "height": 960}
    context = browser.new_context(**kwargs)
    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_selector("text=Control Tower", timeout=120000)
    time.sleep(2)
    return pw, browser, context, page


def with_recording(stem: str):
    tmp = OUT / "_rec" / stem
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    return launch(tmp), tmp


def finish_page_recording(context, page, dest: Path) -> None:
    import subprocess
    video = page.video
    page.close()
    raw = Path(video.path()) if video else None
    context.close()
    if not raw or not raw.exists():
        raise RuntimeError(f"no video for {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(raw)],
        capture_output=True, text=True, check=True,
    )
    dur = float(probe.stdout.strip() or "0")
    args = ["ffmpeg", "-y", "-i", str(raw)]
    if dur < 3.0:
        args += ["-vf", f"tpad=stop_mode=clone:stop_duration={3.0 - dur},fps=30,format=yuv420p"]
    else:
        args += ["-vf", "fps=30,format=yuv420p"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(dest)]
    subprocess.run(args, check=True, capture_output=True)
    raw.unlink(missing_ok=True)
