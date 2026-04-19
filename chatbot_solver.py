"""
chatbot_solver.py — Browser-tab chatbot solver (auto-mcgraw approach)

Instead of direct API calls, opens a real browser tab with ChatGPT / Gemini /
DeepSeek, types the question, waits for the AI response, and reads it back.

No API keys required — the solver reuses your logged-in chatbot session.

Architecture credit: GooglyBlox/auto-mcgraw
  https://github.com/GooglyBlox/auto-mcgraw

Differences from the Chrome extension:
  • We use Playwright to drive the chatbot page instead of content scripts
  • The chatbot tab opens in the SAME browser context as ALEKS (shared cookies)
  • The full ALEKS system prompt is injected so the chatbot returns our JSON format

Set in config.py:
    SOLVER_BACKEND   = "chatbot"
    CHATBOT_PROVIDER = "chatgpt"   # or "gemini" / "deepseek"
"""

import json
import logging
import re
import time
from pathlib import Path

import config

log = logging.getLogger("chatbot_solver")


class ChatbotSolver:
    """
    Drop-in replacement for Solver / CloudSolver.
    Opens a real chatbot tab and drives it with Playwright.

    Same public interface:
        solve(question, context)                                   → str
        solve_from_screenshot(image_path, dom_text, context, ...)  → (str, None)
        bust_cache(question)
        stats  (property)
        close()
    """

    PROVIDER_URLS = {
        "chatgpt":  "https://chatgpt.com",
        "gemini":   "https://gemini.google.com/app",
        "deepseek": "https://chat.deepseek.com",
    }

    def __init__(self, browser):
        """
        browser : AleksBrowser — must already be launched.
        The chatbot tab is opened inside the same Playwright context so the
        user's existing login session (cookies) is shared automatically.
        The tab is opened IMMEDIATELY (same as ALEKS does in launch()).
        """
        self._browser   = browser
        self._chat_page = None
        self.provider   = config.CHATBOT_PROVIDER
        self.model      = self.provider             # shown in the report
        self.api_calls = 0

        if self.provider not in self.PROVIDER_URLS:
            raise ValueError(
                f"Unknown CHATBOT_PROVIDER: {self.provider!r}. "
                "Choose 'chatgpt', 'gemini', or 'deepseek'."
            )

        # Open the chatbot tab immediately — same pattern as AleksBrowser.launch()
        # so the user can log in before the first question is reached.
        self._open_chatbot()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Chatbot tab management
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _open_chatbot(self):
        """
        Open the chatbot in a new tab, initialized exactly like AleksBrowser does.

        Mirrors AleksBrowser.launch():
          1. new_page() inside the same Playwright context (shares cookies)
          2. set_default_timeout — same value as ALEKS
          3. bring_to_front()    — make it visible to the user
          4. goto() + wait for networkidle
          5. Login wall check — pause up to 3 min if needed
          6. bring ALEKS tab back to front so automation continues there
        """
        if self._chat_page is not None:
            return self._chat_page

        url = self.PROVIDER_URLS[self.provider]
        log.info(f"  Opening {self.provider} tab → {url}")

        # ── Open new tab in the same context (same as ALEKS page) ────────
        self._chat_page = self._browser._context.new_page()
        self._chat_page.set_default_timeout(config.TIMEOUT)   # same as ALEKS
        self._chat_page.bring_to_front()                       # make it visible

        self._chat_page.goto(url, timeout=60_000)
        self._chat_page.wait_for_load_state("domcontentloaded", timeout=30_000)
        time.sleep(3)

        # ── Login wall check ──────────────────────────────────────────────
        if self._needs_login():
            print(
                f"\n\033[1;93m"
                f"  ⚠️  {self.provider.upper()} requires login.\n"
                f"  Please sign in in the browser window now.\n"
                f"  The script will wait up to 3 minutes...\n"
                f"\033[0m",
                flush=True,
            )
            deadline = time.time() + 180
            while time.time() < deadline:
                time.sleep(5)
                if not self._needs_login():
                    log.info(f"  Logged in to {self.provider} ✓")
                    time.sleep(2)
                    break
            else:
                raise RuntimeError(
                    f"Login to {self.provider} timed out (3 min). "
                    "Please log in and restart the script."
                )

        log.info(f"  {self.provider} ready ✓")

        # ── Hand focus back to the ALEKS tab ─────────────────────────────
        # Same pattern as navigating between pages in a multi-tab session.
        try:
            self._browser.page.bring_to_front()
        except Exception:
            pass

        return self._chat_page

    def _needs_login(self) -> bool:
        p = self._chat_page
        try:
            if self.provider == "chatgpt":
                return bool(
                    p.query_selector('button:has-text("Log in")') or
                    p.query_selector('button:has-text("Sign up")') or
                    p.query_selector('h1:has-text("ChatGPT")')     # landing page
                )
            elif self.provider == "gemini":
                return bool(
                    p.query_selector('a:has-text("Sign in")') or
                    p.query_selector('button:has-text("Sign in")')
                )
            elif self.provider == "deepseek":
                return bool(
                    p.query_selector('button:has-text("Login")') or
                    p.query_selector('button:has-text("Sign In")')
                )
        except Exception:
            pass
        return False

    def close(self):
        """Close the chatbot tab cleanly at the end of the session."""
        if self._chat_page:
            try:
                self._chat_page.close()
            except Exception:
                pass
            self._chat_page = None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  ChatGPT driver
    #  Mirrors: content-scripts/chatgpt.js in auto-mcgraw
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _ask_chatgpt(self, prompt: str, image_path: Path | None = None) -> str:
        p = self._open_chatbot()
        p.bring_to_front()

        # ── 1. Find input ─────────────────────────────────────────────────
        input_el = None
        for sel in ['#prompt-textarea', 'div[contenteditable="true"]',
                    'textarea[placeholder*="Message" i]', 'textarea']:
            try:
                el = p.wait_for_selector(sel, timeout=10_000)
                if el and el.is_visible():
                    input_el = el
                    log.info(f"  ChatGPT input: {sel}")
                    break
            except Exception:
                continue

        if not input_el:
            raise RuntimeError("ChatGPT input field not found")

        # ── 1.5. Upload image if provided ─────────────────────────────────
        if image_path and image_path.exists():
            file_input = p.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(str(image_path.absolute()))
                log.info(f"  ChatGPT image uploaded: {image_path.name}")
                time.sleep(2)

        # ── 2. Type prompt ────────────────────────────────────────────────
        input_el.click()
        time.sleep(0.3)
        p.keyboard.press("Control+a")
        p.keyboard.press("Delete")
        time.sleep(0.1)
        # Fast type — we only care about the chatbot reading it, not ALEKS
        p.keyboard.type(prompt, delay=3)
        time.sleep(0.5)

        # ── 3. Send ───────────────────────────────────────────────────────
        sent = False
        for sel in ['button[data-testid="send-button"]',
                    'button[aria-label*="Send" i]',
                    '[data-testid="fruitjuice-send-button"]']:
            try:
                btn = p.query_selector(sel)
                if btn and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    sent = True
                    log.info("  ChatGPT: sent ✓")
                    break
            except Exception:
                continue
        if not sent:
            input_el.press("Enter")

        time.sleep(2)

        # ── 4. Wait for streaming to finish ───────────────────────────────
        # Same logic as auto-mcgraw: wait until the stop button disappears
        try:
            p.wait_for_function(
                """() => {
                    const stop = document.querySelector(
                        'button[data-testid="stop-button"], button[aria-label*="Stop" i]'
                    );
                    return !stop || stop.offsetParent === null;
                }""",
                timeout=180_000,
            )
        except Exception:
            log.warning("  ChatGPT: response timeout — reading what's available")

        time.sleep(1)

        # ── 5. Extract response ───────────────────────────────────────────
        # Mirrors auto-mcgraw: prefer code block JSON, fall back to full text
        response = p.evaluate("""
            () => {
                const msgs = Array.from(
                    document.querySelectorAll('[data-message-author-role="assistant"]')
                );
                if (!msgs.length) return '';
                const last = msgs[msgs.length - 1];
                // Prefer JSON code block (auto-mcgraw strategy)
                const code = last.querySelector(
                    'code.language-json, code.hljs, pre code, code'
                );
                if (code) return code.textContent || '';
                return last.textContent || '';
            }
        """)

        log.info(f"  ChatGPT: {len(response)} chars received")
        # Hand focus back to ALEKS so the answer can be typed there
        try:
            self._browser.page.bring_to_front()
        except Exception:
            pass
        return response.strip()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Gemini driver
    #  Mirrors: content-scripts/gemini.js in auto-mcgraw
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _ask_gemini(self, prompt: str, image_path: Path | None = None) -> str:
        p = self._open_chatbot()
        p.bring_to_front()

        # ── 1. Find input (Quill editor) ──────────────────────────────────
        input_el = None
        for sel in ['.ql-editor', 'rich-textarea', '[contenteditable="true"]']:
            try:
                el = p.wait_for_selector(sel, timeout=10_000)
                if el and el.is_visible():
                    input_el = el
                    log.info(f"  Gemini input: {sel}")
                    break
            except Exception:
                continue

        if not input_el:
            raise RuntimeError("Gemini input field not found")

        # ── 1.5. Inject Image via Clipboard Paste (Bulletproof method) ────
        if image_path and image_path.exists():
            try:
                import base64
                with open(image_path, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')
                
                # Base64 string -> Blob -> File -> ClipboardEvent -> Paste
                script = f"""
                (el) => {{
                    const b64 = "{img_data}";
                    const byteChars = atob(b64);
                    const byteNums = new Array(byteChars.length);
                    for (let i = 0; i < byteChars.length; i++) {{
                        byteNums[i] = byteChars.charCodeAt(i);
                    }}
                    const byteArray = new Uint8Array(byteNums);
                    const blob = new Blob([byteArray], {{type: 'image/png'}});
                    const file = new File([blob], "{image_path.name}", {{type: 'image/png'}});
                    
                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(file);
                    
                    const evt = new ClipboardEvent('paste', {{
                        clipboardData: dataTransfer,
                        bubbles: true,
                        cancelable: true
                    }});
                    el.dispatchEvent(evt);
                }}
                """
                input_el.click()
                time.sleep(0.3)
                input_el.evaluate(script)
                log.info(f"  Gemini image pasted via DataTransfer: {image_path.name}")
                time.sleep(1.5) # Wait for Gemini UI to register the image attachment
            except Exception as e:
                log.warning(f"  Failed to paste image to Gemini: {e}")

        # ── 2. Inject text via Playwright Keyboard ────────────────────────
        input_el.click()
        time.sleep(0.3)
        p.keyboard.press("Control+a")
        p.keyboard.press("Delete")
        time.sleep(0.1)
        p.keyboard.insert_text(prompt)
        time.sleep(0.5)

        # ── Force React to register input ────────────────────────────────
        # insert_text bypasses keyboard events so React state doesn't update.
        # Space + Backspace fires real key events to trigger React's onChange.
        p.keyboard.press("Space")
        time.sleep(0.1)
        p.keyboard.press("Backspace")
        time.sleep(0.1)

        # Re-click the input to ensure focus is here (image paste can steal focus)
        input_el.click()
        time.sleep(0.2)

        # Capture baseline BEFORE sending
        baseline = p.evaluate(
            "() => document.querySelectorAll('model-response, .model-response').length"
        )

        # ── Send: click Send button first, Enter as fallback ─────────────
        sent = False
        for sel in [
            'button[aria-label*="Send" i]',
            'button[aria-label*="Enviar" i]',
            'button[aria-label*="send message" i]',
            '[data-test-id="send-button"]',
            'button[jsname][class*="send" i]',
        ]:
            try:
                btn = p.query_selector(sel)
                if btn and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    sent = True
                    log.info(f"  Gemini: sent via button ({sel}) ✓")
                    break
            except Exception:
                continue

        if not sent:
            p.keyboard.press("Enter")
            log.info("  Gemini: sent via Enter ✓")

        # ── Phase 1: wait for generation to START ─────────────────────────
        # Gemini shows a "Stop" button while streaming — wait for it to appear.
        try:
            p.wait_for_function(
                """() => {
                    const stop = document.querySelector(
                        'button[aria-label*="Stop" i], button[aria-label*="Detener" i], ' +
                        'button[aria-label*="stop generating" i]'
                    );
                    return (stop && stop.offsetParent !== null) ||
                           document.querySelectorAll('model-response, .model-response').length > """ +
                           str(baseline) + """;
                }""",
                timeout=30_000,
            )
            log.info("  Gemini: generation started ✓")
        except Exception:
            log.warning("  Gemini: could not detect generation start — proceeding")

        # ── Phase 2: wait for generation to FINISH ────────────────────────
        # Stop button disappears AND send button re-enables
        try:
            p.wait_for_function(
                """() => {
                    const stop = document.querySelector(
                        'button[aria-label*="Stop" i], button[aria-label*="Detener" i], ' +
                        'button[aria-label*="stop generating" i]'
                    );
                    if (stop && stop.offsetParent !== null) return false;
                    const send = document.querySelector(
                        'button[aria-label*="Send" i], button[aria-label*="Enviar" i]'
                    );
                    return !send || !send.disabled;
                }""",
                timeout=180_000,
            )
            log.info("  Gemini: streaming finished ✓")
        except Exception:
            log.warning("  Gemini: response timeout — reading what's available")

        # ── Phase 3: stability check — wait until text stops changing ─────
        # Gemini sometimes appends footnotes or formatting after the stop button hides.
        def _read_last_response() -> str:
            return p.evaluate("""
                () => {
                    const els = document.querySelectorAll(
                        'model-response, .model-response, message-content'
                    );
                    if (!els.length) return '';
                    const last = els[els.length - 1];
                    const code = last.querySelector('code');
                    if (code) return code.textContent || '';
                    return last.textContent || '';
                }
            """)

        prev = _read_last_response()
        for attempt in range(6):          # up to ~12 s of stability checks
            time.sleep(2)
            curr = _read_last_response()
            if curr == prev:
                log.info(f"  Gemini: response stable after {attempt + 1} check(s) ✓")
                break
            log.info(f"  Gemini: still updating ({len(prev)} → {len(curr)} chars)…")
            prev = curr
        else:
            log.warning("  Gemini: response kept changing — using last snapshot")

        response = prev
        log.info(f"  Gemini: {len(response)} chars received")
        try:
            self._browser.page.bring_to_front()
        except Exception:
            pass
        return response.strip()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  DeepSeek driver
    #  Mirrors: content-scripts/deepseek.js in auto-mcgraw
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _ask_deepseek(self, prompt: str) -> str:
        p = self._open_chatbot()
        p.bring_to_front()

        # ── 1. Find input (multiple selector strategies like auto-mcgraw) ─
        input_el = None
        for sel in ['textarea#chat-input',
                    'textarea[placeholder*="Message" i]',
                    'textarea[placeholder*="Send" i]',
                    '[contenteditable="true"]',
                    'textarea']:
            try:
                el = p.wait_for_selector(sel, timeout=10_000)
                if el and el.is_visible():
                    input_el = el
                    log.info(f"  DeepSeek input: {sel}")
                    break
            except Exception:
                continue

        if not input_el:
            raise RuntimeError("DeepSeek input field not found")

        # ── 2. Fill input (auto-mcgraw: triggers input + change events) ───
        input_el.click()
        time.sleep(0.3)
        # Fill via JS to ensure React/Vue state updates
        p.evaluate(
            """([sel, text]) => {
                const el = document.querySelector(sel) || document.querySelector('textarea');
                if (!el) return;
                const nativeInput = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                );
                if (nativeInput) nativeInput.set.call(el, text);
                else el.value = text;
                el.dispatchEvent(new Event('input',  { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            ['textarea', prompt],
        )
        time.sleep(0.5)

        # ── 3. Count baseline messages, then send ─────────────────────────
        baseline = p.evaluate(
            "() => document.querySelectorAll('[class*=\"message\"], [class*=\"chat-message\"]').length"
        )

        sent = False
        for sel in ['button[aria-label*="Send" i]', 'button[type="submit"]']:
            try:
                btn = p.query_selector(sel)
                if btn and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    sent = True
                    log.info("  DeepSeek: sent ✓")
                    break
            except Exception:
                continue
        if not sent:
            input_el.press("Enter")

        time.sleep(2)

        # ── 4. Wait for generation to stop (polling + stop-btn check) ─────
        # Mirrors auto-mcgraw's startObserving + setInterval approach
        try:
            p.wait_for_function(
                f"""() => {{
                    const msgs = document.querySelectorAll(
                        '[class*="message"], [class*="chat-message"]'
                    );
                    if (msgs.length <= {baseline}) return false;
                    const stop = document.querySelector(
                        'button[aria-label*="Stop" i], button[class*="stop"]'
                    );
                    return !stop || stop.offsetParent === null;
                }}""",
                timeout=180_000,
            )
        except Exception:
            log.warning("  DeepSeek: response timeout — reading what's available")

        time.sleep(1)

        # ── 5. Extract last AI message (auto-mcgraw: scan for JSON) ───────
        response = p.evaluate("""
            () => {
                const msgs = Array.from(
                    document.querySelectorAll('[class*="message"], [class*="chat-message"]')
                );
                // Walk from bottom, find last non-user message
                for (let i = msgs.length - 1; i >= 0; i--) {
                    const cls = (msgs[i].className || '').toLowerCase();
                    if (cls.includes('user') || cls.includes('human')) continue;
                    const code = msgs[i].querySelector('code');
                    if (code) return code.textContent || '';
                    return msgs[i].textContent || '';
                }
                return msgs.length ? msgs[msgs.length - 1].textContent : '';
            }
        """)

        log.info(f"  DeepSeek: {len(response)} chars received")
        try:
            self._browser.page.bring_to_front()
        except Exception:
            pass
        return response.strip()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Answer extraction
    #  Mirrors auto-mcgraw's JSON extraction + zero-width char cleaning
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _extract_answer(self, raw: str) -> tuple[str, str]:
        """
        Parse the chatbot response into (answer_json, instructions).

        Expected shape from the new system prompt:
          {"instructions": "...", "answer": { <answer object> }}

        Falls back gracefully to the old bare-answer format so existing
        responses (without "instructions") still work.

        Returns:
          (answer_str, instructions_str)
          answer_str       — JSON string ready for ALEKSInputLayer
          instructions_str — human-readable input description (may be "")
        """
        text = raw.strip()

        # 1. Clean zero-width chars
        text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)

        # 2. Extract JSON — fenced block first, then bare object
        json_str = None

        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
        if m:
            json_str = m.group(1).strip()

        if json_str is None and text.lstrip().startswith('{'):
            candidate = re.search(r'\{.*\}', text, re.DOTALL)
            if candidate:
                try:
                    json.loads(candidate.group(0))
                    json_str = candidate.group(0).strip()
                except Exception:
                    pass

        if json_str is None:
            for m in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}', text, re.DOTALL):
                try:
                    data = json.loads(m.group(0))
                    if isinstance(data, dict) and (
                        "type" in data or "answer" in data or "instructions" in data
                    ):
                        json_str = m.group(0).strip()
                        break
                except Exception:
                    continue

        # 3. Try to parse the new {instructions, answer} wrapper
        if json_str:
            try:
                data = json.loads(json_str)
                if isinstance(data, dict) and "answer" in data:
                    instructions = str(data.get("instructions", ""))
                    answer_obj   = data["answer"]
                    answer_str   = (
                        json.dumps(answer_obj)
                        if isinstance(answer_obj, dict)
                        else str(answer_obj)
                    )
                    return answer_str, instructions
                # Old format — no wrapper, just the answer object directly
                if isinstance(data, dict) and ("type" in data or "value" in data):
                    return json_str, ""
            except Exception:
                pass

        # 4. \boxed{} fallback
        m = re.search(r'\\boxed\{([^}]+)\}', text)
        if m:
            return m.group(1).strip(), ""

        # 5. Last non-empty line
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return (lines[-1] if lines else text), ""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Vision helpers (DOM fallback)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _ask_simple(self, prompt: str, image_path: Path | None = None) -> str:
        """
        Send a plain prompt directly to the chatbot, bypassing the ALEKS
        system prompt. Used for quick classification questions.
        """
        try:
            if self.provider == "chatgpt":
                return self._ask_chatgpt(prompt, image_path)
            elif self.provider == "gemini":
                return self._ask_gemini(prompt, image_path)
            elif self.provider == "deepseek":
                return self._ask_deepseek(prompt)
        except Exception as e:
            log.warning(f"  _ask_simple error: {e}")
        return ""

    def classify_result(self, screenshot_path: Path) -> str:
        """
        Ask the chatbot whether the submitted answer was correct or incorrect.
        Used as a fallback when DOM inspection is inconclusive.

        Returns 'correct', 'incorrect', or 'unknown'.
        """
        prompt = (
            "Look at this ALEKS screenshot carefully. "
            "Was the submitted answer marked as Correct or Incorrect? "
            "Reply with exactly one word: correct, incorrect, or unknown."
        )
        log.info("  classify_result: asking chatbot for result classification...")
        raw = self._ask_simple(prompt, screenshot_path).strip().lower()
        raw = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', raw)
        if "incorrect" in raw:
            return "incorrect"
        if "correct" in raw:
            return "correct"
        return "unknown"

    def classify_graph_axes(self, screenshot_path: Path) -> dict | None:
        """
        Ask the chatbot to read the axis ranges from a graph screenshot.
        Used when canvas data-attributes are absent.

        Returns {"xMin": float, "xMax": float, "yMin": float, "yMax": float}
        or None on failure.
        """
        prompt = (
            "Look at this ALEKS graph screenshot. "
            "What are the minimum and maximum values on the x-axis and y-axis? "
            "Reply with ONLY a JSON object like: "
            '{"xMin": -10, "xMax": 10, "yMin": -10, "yMax": 10}'
        )
        log.info("  classify_graph_axes: asking chatbot for axis ranges...")
        raw = self._ask_simple(prompt, screenshot_path).strip()
        raw = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', raw)
        m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                return {
                    "xMin": float(data.get("xMin", -10)),
                    "xMax": float(data.get("xMax",  10)),
                    "yMin": float(data.get("yMin", -10)),
                    "yMax": float(data.get("yMax",  10)),
                }
            except Exception:
                pass
        log.warning("  classify_graph_axes: could not parse axes from chatbot response")
        return None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Public interface
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def solve(self, question: str, context: str = "", image_path: Path | None = None) -> str:
        """
        Ask the chatbot and return the ALEKS-formatted answer.
        Same signature as Solver.solve.
        """
        # Full prompt: our ALEKS system prompt + context + question
        # The system prompt tells the chatbot exactly which JSON format to return
        if context:
            prompt = (
                f"{config.SYSTEM_PROMPT}\n\n"
                f"=== CONTEXT ===\n{context}\n\n"
                f"=== QUESTION ===\n{question}"
            )
        else:
            prompt = f"{config.SYSTEM_PROMPT}\n\n{question}"

        self.api_calls += 1
        DIM   = "\033[2;90m"
        BRIGHT = "\033[1;96m"
        RESET  = "\033[0m"
        print(f"{DIM}{'─' * 60}{RESET}", flush=True)
        log.info(f"  Asking {self.provider}...")

        try:
            if self.provider == "chatgpt":
                raw = self._ask_chatgpt(prompt, image_path)
            elif self.provider == "gemini":
                raw = self._ask_gemini(prompt, image_path)
            elif self.provider == "deepseek":
                raw = self._ask_deepseek(prompt)  # DeepSeek web doesn't support images well
            else:
                raise ValueError(f"Unknown provider: {self.provider}")
        except Exception as e:
            log.error(f"  {self.provider} error: {e}")
            print(f"{DIM}{'─' * 60}{RESET}", flush=True)
            return ""

        print(f"{BRIGHT}✨ Response: {raw[:300]}{RESET}", flush=True)
        print(f"{DIM}{'─' * 60}{RESET}", flush=True)

        answer, instructions = self._extract_answer(raw)
        if instructions:
            print(f"\033[2;37m  📋 Instructions: {instructions[:200]}\033[0m", flush=True)
        log.info(f"  Answer: {answer}")
        return answer, instructions

    def solve_from_screenshot(
        self,
        image_path: Path,
        dom_text:   str = "",
        context:    str = "",
    ) -> tuple[str, str]:
        """
        Solve an ALEKS question using the screenshot + DOM text.

        Returns (answer_str, instructions_str).
        """
        if not image_path.exists():
            log.warning(f"  Screenshot not found: {image_path}")
            return "", ""

        question_text = dom_text if dom_text else "Please provide the final answer for the attached image."
        answer, instructions = self.solve(question_text, context=context, image_path=image_path)
        return answer, instructions

    @property
    def stats(self) -> dict:
        return {
            "api_calls":    self.api_calls,
            "total_tokens": 0,    # not tracked for web chatbots
        }
