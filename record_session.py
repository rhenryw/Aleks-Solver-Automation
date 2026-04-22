#!/usr/bin/env python3
"""
record_session.py — ALEKS interaction recorder.

Use this to record yourself doing an ALEKS assignment manually.
The recording captures every click, input, navigation, and screenshot
so the automation code can be improved to match exactly how ALEKS works.

Usage:
    # Start fresh at the ALEKS login page
    python3 record_session.py

    # Start via an SSO link (Canvas / LMS)
    python3 record_session.py --sso "https://secure.aleks.com/service?account=sso&..."

    # Start at any URL you like
    python3 record_session.py --url "https://www.aleks.com/student/home"

    # Label the recording folder for easy identification
    python3 record_session.py --sso "..." --label "precalc-activity-3"

    # Replay a previous session's cookies/state so you skip login
    python3 record_session.py --resume

After the session, a folder is created under recordings/ containing:
    events.jsonl    — every interaction as newline-delimited JSON
    timeline.md     — human-readable chronological summary
    summary.json    — stats + file index
    snapshots/      — screenshot + HTML at each key interaction
    videos/         — full-session screen recording
    downloads/      — any files downloaded during the session
    trace.zip       — Playwright trace (open with: playwright show-trace)
    session_state.json — cookies/storage saved for --resume
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import signal
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

# ─── Paths ──────────────────────────────────────────────────────
ROOT = Path(__file__).parent
RECORDINGS_DIR = ROOT / "recordings"
STATE_FILE = ROOT / ".aleks_session_state.json"

# ─── Tuning ─────────────────────────────────────────────────────
MAX_SNAPSHOTS = 300          # cap total screenshots per session
STATE_SAVE_INTERVAL = 15     # seconds between auto-saves of cookies
MIN_SNAPSHOT_GAP = 0.5       # seconds between snapshots for rapid events

SNAPSHOT_EVENT_TYPES = {
    "page-opened",
    "page-ready",
    "navigation",
    "click",
    "change",
    "submit",
    "download",
    "dialog",
    "keydown",
}

# ─── Browser instrumentation injected into every page ───────────
INSTRUMENTATION_JS = r"""
(() => {
  if (window.__aleksRecorderInstalled) return;
  window.__aleksRecorderInstalled = true;

  const MAX_TEXT = 220;

  const clip = (v) => {
    if (typeof v !== "string") return "";
    const s = v.replace(/\s+/g, " ").trim();
    return s.length > MAX_TEXT ? s.slice(0, MAX_TEXT) + "…" : s;
  };

  const escapeCss = (v) => {
    if (window.CSS?.escape) return window.CSS.escape(v);
    return String(v).replace(/([^a-zA-Z0-9_-])/g, "\\$1");
  };

  const attrSel = (name, val) => `[${name}=${JSON.stringify(val)}]`;

  const selector = (el) => {
    if (!(el instanceof Element)) return "";
    const parts = [];
    let cur = el;
    while (cur instanceof Element && parts.length < 6) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) { part += `#${escapeCss(cur.id)}`; parts.unshift(part); break; }
      const tid   = cur.getAttribute("data-testid");
      const name  = cur.getAttribute("name");
      const role  = cur.getAttribute("role");
      const type  = cur.getAttribute("type");
      const cls   = Array.from(cur.classList)
                      .filter(c => !/^css-[a-z0-9]+$/i.test(c))
                      .slice(0, 2);
      if (tid)         part += attrSel("data-testid", tid);
      else if (name)   part += attrSel("name", name);
      else if (role)   part += attrSel("role", role);
      else if (type)   part += attrSel("type", type);
      else if (cls.length) part += "." + cls.map(escapeCss).join(".");
      if (cur.parentElement) {
        const sibs = Array.from(cur.parentElement.children).filter(c => c.tagName === cur.tagName);
        if (sibs.length > 1) part += `:nth-of-type(${sibs.indexOf(cur) + 1})`;
      }
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  };

  const describe = (el) => {
    if (!(el instanceof Element)) return null;
    const type  = (el.getAttribute("type") || "").toLowerCase();
    const ac    = (el.getAttribute("autocomplete") || "").toLowerCase();
    const sens  = type === "password" || ac.includes("password");
    let value = "";
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)
      value = sens ? "[redacted]" : clip(el.value || "");
    else if (el instanceof HTMLSelectElement)
      value = clip(el.value || "");
    else if (el.isContentEditable)
      value = clip(el.textContent || "");

    // ALEKS-specific: capture MathJax/KaTeX rendered text nearby
    let mathText = "";
    const mathEl = el.closest("[class*='question'],[class*='problem'],[class*='math']");
    if (mathEl) mathText = clip(mathEl.innerText || mathEl.textContent || "");

    return {
      tag:         el.tagName.toLowerCase(),
      selector:    selector(el),
      text:        clip(el.innerText || el.textContent || ""),
      mathContext: mathText,
      name:        el.getAttribute("name") || "",
      role:        el.getAttribute("role") || "",
      type,
      placeholder: el.getAttribute("placeholder") || "",
      ariaLabel:   el.getAttribute("aria-label") || "",
      href:        el.getAttribute("href") || "",
      value,
      checked:     "checked" in el ? Boolean(el.checked) : null,
      classes:     Array.from(el.classList).join(" "),
    };
  };

  const send = (payload) => {
    try {
      const fn = window.aleksRecorderEvent;
      if (typeof fn !== "function") return;
      fn(JSON.stringify({
        ...payload,
        url:   window.location.href,
        title: document.title,
        ts:    new Date().toISOString(),
      }));
    } catch(_) {}
  };

  // ── Events ──────────────────────────────────────────────────
  document.addEventListener("click", (e) => {
    send({ type: "click", element: describe(e.target) });
  }, true);

  let lastInput = 0;
  document.addEventListener("input", (e) => {
    const now = Date.now();
    if (now - lastInput < 400) return;
    lastInput = now;
    send({ type: "input", element: describe(e.target) });
  }, true);

  document.addEventListener("change", (e) => {
    send({ type: "change", element: describe(e.target) });
  }, true);

  document.addEventListener("submit", (e) => {
    send({ type: "submit", element: describe(e.target) });
  }, true);

  document.addEventListener("keydown", (e) => {
    if (!["Enter","Tab","Escape","ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)) return;
    send({ type: "keydown", key: e.key, element: describe(e.target) });
  }, true);

  // ── Page ready ──────────────────────────────────────────────
  const ready = () => send({ type: "page-ready" });
  if (document.readyState === "complete" || document.readyState === "interactive")
    queueMicrotask(ready);
  else
    window.addEventListener("DOMContentLoaded", ready, { once: true });
})();
"""


# ─── Utilities ──────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str, default: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned[:80] or default


def summarize_event(ev: dict[str, Any]) -> str:
    t    = ev.get("type", "event")
    url  = ev.get("url") or ev.get("page_url") or ""
    el   = ev.get("element") or {}
    sel  = el.get("selector") or el.get("ariaLabel") or el.get("text") or el.get("tag") or "element"
    val  = el.get("value") or ""
    math = el.get("mathContext") or ""

    if t in {"click", "change", "input", "submit"}:
        line = f"{t}  {sel}"
        if val:   line += f"  value={val!r}"
        if math:  line += f"  [math: {math[:80]}]"
        line += f"  @ {url}"
        return line
    if t == "keydown":    return f"keydown {ev.get('key','')}  @ {url}"
    if t == "navigation": return f"navigation → {url}"
    if t == "download":   return f"download {ev.get('suggested_filename','')}  @ {url}"
    if t == "dialog":     return f"dialog {ev.get('dialog_type','')}: {ev.get('message','')}"
    return f"{t}  @ {url}".strip()


# ─── Recorder ───────────────────────────────────────────────────

class SessionRecorder:
    def __init__(self, run_dir: Path):
        self.run_dir        = run_dir
        self.snapshots_dir  = run_dir / "snapshots"
        self.videos_dir     = run_dir / "videos"
        self.downloads_dir  = run_dir / "downloads"
        self.events_path    = run_dir / "events.jsonl"
        self.timeline_path  = run_dir / "timeline.md"
        self.summary_path   = run_dir / "summary.json"
        self.trace_path     = run_dir / "trace.zip"
        self.state_path     = run_dir / "session_state.json"

        self.started_at = utc_now()
        self._queue: asyncio.Queue[tuple[dict[str, Any], Page | None]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._events: list[dict[str, Any]] = []
        self._page_ids: dict[int, str]     = {}
        self._page_counter   = 0
        self._event_counter  = 0
        self._snapshot_counter = 0
        self._last_snap_at: dict[str, float] = {}
        self._stopping = False

    async def install(self, context: BrowserContext) -> None:
        for d in (self.run_dir, self.snapshots_dir, self.videos_dir, self.downloads_dir):
            d.mkdir(parents=True, exist_ok=True)

        self._worker_task = asyncio.create_task(self._consume())

        await context.expose_binding("aleksRecorderEvent", self._on_browser_event)
        await context.add_init_script(INSTRUMENTATION_JS)

        for page in context.pages:
            await self._attach(page)
        context.on("page", lambda p: asyncio.create_task(self._attach(p)))

    async def _attach(self, page: Page) -> None:
        key = id(page)
        if key in self._page_ids:
            return
        self._page_counter += 1
        pid = f"page-{self._page_counter:02d}"
        self._page_ids[key] = pid

        opener = None
        try:
            opener = await page.opener()
        except Exception:
            pass

        await self._enqueue({
            "type":           "page-opened",
            "page_id":        pid,
            "url":            page.url,
            "opener_page_id": self._page_ids.get(id(opener)) if opener else None,
        }, page)

        page.on("framenavigated",
            lambda frame: asyncio.create_task(self._on_nav(page, frame)))
        page.on("download",
            lambda dl: asyncio.create_task(self._on_download(page, dl)))
        page.on("dialog",
            lambda dlg: asyncio.create_task(self._on_dialog(page, dlg)))
        page.on("close",
            lambda: asyncio.create_task(
                self._enqueue({"type": "page-closed", "page_id": pid}, None)))

    async def _on_browser_event(self, source: Any, raw: str) -> None:
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            return

        page  = source.get("page")
        frame = source.get("frame")

        if page is not None:
            await self._attach(page)
            ev["page_id"]  = self._page_ids.get(id(page))
            ev["page_url"] = page.url
        if frame is not None:
            ev["frame_url"]      = frame.url
            ev["is_main_frame"]  = page is not None and frame == page.main_frame

        # Skip page-ready events from iframes (ALEKS embeds many)
        if ev.get("type") == "page-ready" and not ev.get("is_main_frame", True):
            return

        await self._enqueue(ev, page)

    async def _on_nav(self, page: Page, frame: Any) -> None:
        if frame != page.main_frame:
            return
        await self._enqueue({
            "type":    "navigation",
            "page_id": self._page_ids.get(id(page)),
            "url":     frame.url,
        }, page)

    async def _on_download(self, page: Page, dl: Any) -> None:
        name = dl.suggested_filename or "download"
        dest = self.downloads_dir / f"{int(time.time()*1000)}-{slugify(name)}"
        failure = None
        try:
            await dl.save_as(str(dest))
        except Exception as exc:
            failure = str(exc)

        await self._enqueue({
            "type":               "download",
            "page_id":            self._page_ids.get(id(page)),
            "url":                page.url,
            "suggested_filename": name,
            "saved_path":         str(dest.relative_to(self.run_dir)) if dest.exists() else None,
            "failure":            failure,
        }, page)

    async def _on_dialog(self, page: Page, dlg: Any) -> None:
        await self._enqueue({
            "type":          "dialog",
            "page_id":       self._page_ids.get(id(page)),
            "url":           page.url,
            "dialog_type":   dlg.type,
            "message":       dlg.message,
            "default_value": dlg.default_value,
        }, page)

    async def _enqueue(self, ev: dict[str, Any], page: Page | None) -> None:
        if self._stopping:
            return
        ev.setdefault("recorded_at", utc_now())
        await self._queue.put((ev, page))

    async def _consume(self) -> None:
        while True:
            item = await self._queue.get()
            if item == (None, None):
                self._queue.task_done()
                return

            ev, page = item
            self._event_counter += 1
            ev["seq"] = self._event_counter

            if self._should_snap(ev, page):
                ev.update(await self._snap(ev, page))  # type: ignore[arg-type]

            self._events.append(ev)
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, ensure_ascii=True) + "\n")

            self._queue.task_done()

    def _should_snap(self, ev: dict[str, Any], page: Page | None) -> bool:
        if page is None or self._snapshot_counter >= MAX_SNAPSHOTS:
            return False
        if ev.get("type") not in SNAPSHOT_EVENT_TYPES:
            return False
        if ev.get("type") == "page-opened" and ev.get("url") in {"", "about:blank"}:
            return False

        pid  = ev.get("page_id", "page")
        now  = time.monotonic()
        last = self._last_snap_at.get(pid, 0.0)
        if ev.get("type") in {"click", "change", "input", "keydown"} and now - last < MIN_SNAPSHOT_GAP:
            return False

        self._last_snap_at[pid] = now
        self._snapshot_counter += 1
        return True

    async def _snap(self, ev: dict[str, Any], page: Page) -> dict[str, Any]:
        base  = f"{ev['seq']:04d}-{slugify(ev.get('type','ev'))}-{slugify(ev.get('page_id','pg'))}"
        ss    = self.snapshots_dir / f"{base}.png"
        html  = self.snapshots_dir / f"{base}.html"
        title = ""

        ss_rel = html_rel = None
        try:
            await page.screenshot(path=str(ss), full_page=False)
            ss_rel = str(ss.relative_to(self.run_dir))
        except Exception:
            pass
        try:
            html.write_text(await page.content(), encoding="utf-8")
            html_rel = str(html.relative_to(self.run_dir))
        except Exception:
            pass
        try:
            title = await page.title()
        except Exception:
            pass

        return {"snapshot_path": ss_rel, "html_path": html_rel, "page_title": title}

    async def stop(self) -> None:
        self._stopping = True
        await self._queue.join()
        await self._queue.put((None, None))
        if self._worker_task:
            await self._worker_task

    def write_reports(self) -> None:
        counts = Counter(ev.get("type") for ev in self._events)
        urls: list[str] = []
        for ev in self._events:
            u = ev.get("url") or ev.get("page_url")
            if u and u not in urls:
                urls.append(u)

        lines = [
            "# ALEKS Recording Timeline",
            "",
            f"Started : {self.started_at}",
            f"Finished: {utc_now()}",
            f"Events  : {len(self._events)}",
            f"Snapshots: {self._snapshot_counter}",
            "",
            "## Events",
            "",
        ]
        for ev in self._events:
            lines.append(f"- `{ev['seq']:04d}` {summarize_event(ev)}")
        self.timeline_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        summary = {
            "started_at":        self.started_at,
            "finished_at":       utc_now(),
            "event_count":       len(self._events),
            "snapshot_count":    self._snapshot_counter,
            "event_type_counts": dict(counts),
            "urls_visited":      urls,
            "files": {
                "events":        self.events_path.name,
                "timeline":      self.timeline_path.name,
                "trace":         self.trace_path.name if self.trace_path.exists() else None,
                "session_state": self.state_path.name if self.state_path.exists() else None,
                "snapshots_dir": self.snapshots_dir.name,
                "videos_dir":    self.videos_dir.name,
                "downloads_dir": self.downloads_dir.name,
            },
        }
        self.summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


# ─── State auto-saver ───────────────────────────────────────────

async def _autosave_state(context: BrowserContext, path: Path) -> None:
    while True:
        await asyncio.sleep(STATE_SAVE_INTERVAL)
        try:
            await context.storage_state(path=str(path))
        except Exception:
            return


# ─── Main recording loop ────────────────────────────────────────

def _build_run_dir(label: str | None) -> Path:
    RECORDINGS_DIR.mkdir(exist_ok=True)
    ts     = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{slugify(label)}" if label else ""
    return RECORDINGS_DIR / f"{ts}{suffix}"


async def launch(args: argparse.Namespace) -> int:
    use_state = STATE_FILE.exists() and not args.fresh
    run_dir   = _build_run_dir(args.label)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "videos").mkdir(exist_ok=True)

    recorder = SessionRecorder(run_dir)

    # Determine start URL
    if args.sso:
        start_url = args.sso
    elif args.url:
        start_url = args.url
    elif use_state:
        start_url = "https://www.aleks.com/student/home"
    else:
        start_url = "https://www.aleks.com/login"

    print()
    print("=" * 58)
    print("  ALEKS Session Recorder")
    print("=" * 58)
    print(f"  Recording folder : {run_dir.relative_to(ROOT)}")
    print(f"  Starting URL     : {start_url[:72]}")
    print(f"  Saved state      : {'yes (--fresh to ignore)' if use_state else 'no'}")
    print()
    print("  Do your ALEKS assignment normally in the browser.")
    print("  Press  Ctrl+C  here when you are done.")
    print("  (Closing the browser window also stops the recording.)")
    print("=" * 58)
    print()

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=False,
            slow_mo=args.slow_mo,
            args=["--start-maximized"],
        )

        ctx_kwargs: dict[str, Any] = {
            "accept_downloads": True,
            "record_video_dir": str(run_dir / "videos"),
            "viewport":         None,   # None = use window size (maximized)
            "no_viewport":      True,
        }
        if use_state:
            ctx_kwargs["storage_state"] = str(STATE_FILE)

        context = await browser.new_context(**ctx_kwargs)
        await recorder.install(context)
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)

        saver_task = asyncio.create_task(_autosave_state(context, recorder.state_path))

        page = await context.new_page()
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"  [warning] Initial navigation: {exc}")

        # Wait for stop signal
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        browser.on("disconnected", lambda: stop.set())
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass

        try:
            await stop.wait()
        finally:
            # Save session state globally so --resume works next time
            for dest in (recorder.state_path, STATE_FILE):
                try:
                    await context.storage_state(path=str(dest))
                except Exception:
                    pass

            saver_task.cancel()

            try:
                await context.tracing.stop(path=str(recorder.trace_path))
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            try:
                await saver_task
            except asyncio.CancelledError:
                pass

        await recorder.stop()

    recorder.write_reports()

    print()
    print("Recording saved:")
    for label, path in [
        ("Events",    recorder.events_path),
        ("Timeline",  recorder.timeline_path),
        ("Summary",   recorder.summary_path),
        ("Trace",     recorder.trace_path),
        ("Snapshots", recorder.snapshots_dir),
        ("Videos",    recorder.videos_dir),
    ]:
        if path.exists():
            print(f"  {label:<10} {path.relative_to(ROOT)}")

    print()
    if recorder.trace_path.exists():
        print(f"  View trace:  playwright show-trace {recorder.trace_path.relative_to(ROOT)}")
    print()
    return 0


# ─── CLI ────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record an ALEKS session so the automation can be improved.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sso",
        metavar="URL",
        help="SSO link from Canvas/LMS. Opens it directly, skipping the normal login page.",
    )
    parser.add_argument(
        "--url",
        metavar="URL",
        help="Custom starting URL (overridden by --sso if both are given).",
    )
    parser.add_argument(
        "--resume",
        dest="fresh",
        action="store_false",
        default=False,
        help="(default) Re-use saved cookies from the last session to skip login.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore saved cookies and start a clean session.",
    )
    parser.add_argument(
        "--label",
        metavar="NAME",
        help="Short label appended to the recording folder name (e.g. 'activity-3').",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        metavar="MS",
        help="Slow every browser action by N milliseconds (useful for debugging).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(launch(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
