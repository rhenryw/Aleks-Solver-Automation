"""
browser.py — ALEKS-specific Playwright automation.

Selectors in this file come from a real recorded session
(see record_session.py) not guesses. Key observations:

  * After SSO, ALEKS routes you to:  .../Isl.exe/...#home
  * Clicking #smt_bottomnav_button_input_start_learning moves you
    to the learning queue:           .../Isl.exe/...#item
  * On #item the problem lives inside an ALEKS "ansed" widget:
        container:    #ansed_root_ansed_1        (or _1_1, _1_2…)
        input fields: #ansed_input_ansed_1       (or _1_1, _1_2…)
  * Bottom-nav actions (stable IDs):
        Check Answer        #smt_bottomnav_button_input_checkAnswer
        Continue (correct)  #smt_bottomnav_button_input_learningCorrect
        Skip / New item     #smt_bottomnav_button_input_newItem
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

import config

log = logging.getLogger("browser")


class AutomationError(Exception):
    """Unrecoverable automation failure."""


class AleksBrowser:
    def __init__(self):
        self._pw = None
        self._browser:  Browser | None        = None
        self._context:  BrowserContext | None = None
        self.page:      Page | None           = None
        self.screenshots_dir = Path("screenshots")
        self.screenshots_dir.mkdir(exist_ok=True)
        self.last_notice: str | None = None

    # ─── Lifecycle ──────────────────────────────────────────────

    def launch(self):
        log.info("Launching browser...")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=config.HEADLESS,
            slow_mo=config.SLOW_MO,
            args=["--start-maximized"],
        )
        self._context = self._browser.new_context(
            viewport=None,
            no_viewport=True,
            accept_downloads=True,
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(config.TIMEOUT)
        log.info("Browser ready")

    def close(self):
        try:
            if self._context: self._context.close()
            if self._browser: self._browser.close()
            if self._pw:      self._pw.stop()
        except Exception:
            pass
        log.info("Browser closed")

    def screenshot(self, name: str = "debug"):
        if self.page and config.SCREENSHOT_ON_ERROR:
            path = self.screenshots_dir / f"{name}.png"
            try:
                self.page.screenshot(path=str(path))
                log.info(f"Screenshot saved: {path}")
            except Exception:
                pass

    # ─── Authentication ─────────────────────────────────────────

    def login_sso(self, sso_url: str):
        """
        Follow a Canvas/LMS SSO link into ALEKS.  Waits for the
        redirect chain to land on an authenticated ALEKS page.
        """
        log.info("Logging in via SSO...")
        self.page.goto(sso_url, wait_until="domcontentloaded", timeout=60_000)

        # ALEKS bounces through a few pages; wait until we see the
        # authenticated shell (URL contains "/alekscgi/").
        for _ in range(30):
            try:
                self.page.wait_for_load_state("networkidle", timeout=3_000)
            except Exception:
                pass
            if "/alekscgi/" in self.page.url:
                break
            time.sleep(1)

        if "login" in self.page.url.lower() or "service?account=sso" in self.page.url:
            self.screenshot("sso_login_failed")
            raise AutomationError(
                "SSO login appears to have failed. Generate a fresh link — "
                "they expire quickly — and try again."
            )

        log.info(f"SSO login OK (landed on {self.page.url[:70]}...)")

    # ─── Navigation ─────────────────────────────────────────────

    def wait_for_home(self, timeout: float = 30.0):
        """Wait until we're on an ALEKS page with a #home fragment."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if config.URL_FRAGMENT_HOME in self.page.url:
                try:
                    self.page.wait_for_load_state("networkidle", timeout=3_000)
                except Exception:
                    pass
                return
            time.sleep(0.5)
        log.warning("Home fragment never appeared; continuing anyway.")

    def _on_my_classes_page(self) -> bool:
        """
        ALEKS routes SSO to a 'My Classes' dashboard on www-awa.aleks.com.
        The Start Learning button is NOT here — we first have to click the
        class card to enter that class's workspace on www-awy.aleks.com.
        Detect by URL only (title() can throw mid-navigation).
        """
        try:
            url = self.page.url or ""
        except Exception:
            url = ""
        return "www-awa.aleks.com" in url

    def select_class(self, class_name_substring: str | None = None):
        """
        Click a class card on the 'My Classes' page.

        DOM captured from the recording:

            <div role="heading" aria-level="3">
              <div class="tooltip-info-button--...">
                <button type="button" role="link"
                        aria-label="enter MAT 170: Precalculus..."
                        value="MAT 170: Precalculus...">
                  <span>MAT 170: Precalculus...</span>
                </button>
              </div>
            </div>

        The button is not an anchor — its click handler uses JS to navigate
        to a DIFFERENT subdomain (www-awa → www-awy), so we must wrap the
        click in `expect_navigation` and click the inner span the same way
        the user did (plain <button>.click() doesn't always fire ALEKS's
        handler before the card's overlay/loader finishes animating).
        """
        if not self._on_my_classes_page():
            log.info("Not on 'My Classes' page — skipping class selection.")
            return

        log.info("On 'My Classes' page — waiting for class cards to load...")

        # Wait for the main grid to be interactive. The ALEKS "My Classes"
        # page shows a blocking loader until the class list is ready.
        try:
            self.page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass

        # Locate the class entry button. Prefer aria-label match (stable).
        cards = self.page.locator('button[role="link"][aria-label^="enter"]')
        try:
            cards.first.wait_for(state="visible", timeout=15_000)
        except Exception:
            # Fallback selector (older ALEKS skins)
            cards = self.page.locator('div[role="heading"] button[role="link"]')
            try:
                cards.first.wait_for(state="visible", timeout=10_000)
            except Exception:
                self.screenshot("no_class_cards")
                raise AutomationError(
                    "No class cards found on 'My Classes' page after 35s."
                )

        count = cards.count()
        log.info(f"Found {count} class card(s).")

        # Pick the right card
        target = None
        if class_name_substring:
            needle = class_name_substring.lower()
            for i in range(count):
                c = cards.nth(i)
                try:
                    label = (c.get_attribute("aria-label") or "").lower()
                    if needle in label:
                        target = c
                        break
                except Exception:
                    continue
        target = target or cards.first

        try:
            aria = target.get_attribute("aria-label") or ""
        except Exception:
            aria = ""
        log.info(f"  Clicking class: {aria[:70]}")

        # Scroll into view and click the inner span (mirrors the recording).
        try:
            target.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass

        # The recording clicked the inner <span>. Fall back to the button
        # itself if the span isn't addressable.
        click_target = target.locator("span").first
        try:
            click_target.wait_for(state="visible", timeout=2_000)
        except Exception:
            click_target = target

        # Wrap in expect_navigation so we know the click really did its job.
        try:
            with self.page.expect_navigation(
                url=lambda u: "www-awy.aleks.com" in u,
                timeout=30_000,
                wait_until="domcontentloaded",
            ):
                click_target.click()
        except Exception as exc:
            # Some builds replace the page via history.pushState instead of
            # a full navigation; detect that by polling URL after the click.
            log.warning(f"  expect_navigation didn't fire ({exc}); "
                        "polling URL fallback...")
            try:
                click_target.click()
            except Exception:
                pass
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    url = self.page.url
                except Exception:
                    url = ""
                if "www-awy.aleks.com" in url:
                    break
                time.sleep(0.5)
            else:
                self.screenshot("class_no_nav")
                raise AutomationError(
                    "Clicked class card but page never navigated to www-awy."
                )

        log.info(f"  Arrived in class workspace: {self.page.url[:70]}...")

        # Let the class-home dashboard hydrate before the next step.
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

    def start_learning(self, class_name_substring: str | None = None):
        """
        Full flow from wherever SSO landed us to the first problem:

          1. Wait for #home
          2. If on 'My Classes', click into a class
          3. Click Start Learning / Continue My Path
          4. Wait for #item fragment
        """
        self.wait_for_home()
        self.select_class(class_name_substring)
        self.wait_for_home()

        # Sometimes SSO lands us directly on a problem page, or clicking
        # a class skips the "Start Learning" dashboard and goes straight
        # into a question. In that case the Start Learning button never
        # appears — just check whether we're already on a problem.
        if config.URL_FRAGMENT_ITEM in self.page.url or self.has_question():
            log.info("Already on a problem page — skipping Start Learning.")
            return

        log.info("Clicking 'Start Learning' / 'Continue My Path'...")
        selector = config.SELECTORS["start_learning"]
        btn = self.page.locator(selector).first
        try:
            btn.wait_for(state="visible", timeout=30_000)
        except Exception as exc:
            # Maybe we slipped past the dashboard while waiting.
            if config.URL_FRAGMENT_ITEM in self.page.url or self.has_question():
                log.info("Problem appeared while waiting for Start Learning.")
                return
            self.screenshot("no_start_learning")
            raise AutomationError(
                f"Start Learning button never appeared on class home: {exc}"
            )
        try:
            btn.scroll_into_view_if_needed(timeout=3_000)
        except Exception:
            pass
        try:
            btn.click(timeout=8_000)
        except Exception as exc:
            # ALEKS often auto-advances to a problem while we're mid-click
            # (the button disappears under us). If we ended up on an item
            # anyway, that's success.
            if config.URL_FRAGMENT_ITEM in self.page.url or self.has_question():
                log.info("Problem appeared despite Start Learning click error.")
                return
            # Try a JS fallback click — bypasses overlay interception.
            try:
                btn.evaluate("el => el.click()")
            except Exception:
                pass
            # Give it a moment to settle and re-check.
            for _ in range(20):
                if config.URL_FRAGMENT_ITEM in self.page.url or self.has_question():
                    log.info("Problem appeared after JS fallback click.")
                    return
                time.sleep(0.5)
            self.screenshot("start_learning_click_failed")
            raise AutomationError(f"Could not click Start Learning: {exc}")

        # Wait for transition to the problem page
        for _ in range(30):
            if config.URL_FRAGMENT_ITEM in self.page.url:
                log.info("On problem page (#item)")
                return
            time.sleep(0.5)

        log.warning("Did not see #item fragment; may already be on a problem.")

    # ─── Problem detection ──────────────────────────────────────

    def _problem_root(self):
        """Return the ansed answer root element (search main page + iframes)."""
        try:
            el = self.page.query_selector(config.SELECTORS["ansed_root"])
            if el:
                return self.page, el
        except Exception:
            pass

        # Try every iframe
        for frame in self.page.frames:
            try:
                el = frame.query_selector(config.SELECTORS["ansed_root"])
                if el:
                    return frame, el
            except Exception:
                continue
        return None, None

    def _figed_root(self):
        """Return (frame, figed_root_element) if a number-line editor is visible."""
        for frame in [self.page, *self.page.frames]:
            try:
                el = frame.query_selector(config.SELECTORS["figed_root"])
                if el and _is_visible(el):
                    return frame, el
            except Exception:
                continue
        return None, None

    def has_question(self) -> bool:
        """Is there a problem currently displayed?"""
        frame, root = self._problem_root()
        if root is not None:
            return True
        # Number-line / graph-editor problems have no ansed_input.
        _, figed = self._figed_root()
        return figed is not None

    def read_question(self) -> str:
        """
        Extract the current problem's text.

        ALEKS renders math TWICE: once as screen-reader speech
        (e.g. "begin fraction u minus 2 over 3 end fraction") and once
        as visual AnsedObject spans (e.g. "= u 2 3"). The visual spans
        sit inside elements with aria-hidden="true", so we strip those
        subtrees and keep the clean accessible text.
        """
        frame, root = self._problem_root()
        if not root:
            # Fall back to the number-line / figure editor container so the
            # question text (e.g. "Graph the compound inequality ... x > -1 and
            # x < 7") is still extracted for the model.
            frame, root = self._figed_root()
        if not root:
            return ""

        try:
            # Walk up to the step/statement container, then clone it,
            # strip aria-hidden="true" subtrees + ansed answer editors,
            # and return the cleaned innerText.
            js = """
            (el) => {
                // Find the enclosing problem container.  ALEKS wraps each
                // question's body in #algoPrompt (inside #main_algo_body).
                // That is the *only* part we want — everything above it is
                // site chrome ("Skip to Main Content", topic title, etc.).
                const ID_MATCH    = new Set(['algoPrompt', 'main_algo_body',
                                             'step_container']);
                const CLASS_MATCH = ['statement_block_aleks',
                                     'problem_panel',
                                     'main_algo_aleks'];

                let node = el;
                let container = null;
                for (let i = 0; i < 14 && node.parentElement; i++) {
                    node = node.parentElement;
                    if (ID_MATCH.has(node.id) ||
                        CLASS_MATCH.some(c => node.classList.contains(c))) {
                        container = node;
                        break;
                    }
                }
                // Fallback: stay close to the input, don't climb the whole page
                if (!container) {
                    container = el.closest('#algoPrompt, #main_algo_body, .statement_block_aleks, .problem_panel')
                              || el.parentElement;
                }

                const clone = container.cloneNode(true);

                // Remove visual math (duplicates the screen-reader text)
                clone.querySelectorAll('[aria-hidden="true"]').forEach(
                    n => n.remove()
                );

                // Some ALEKS "fill in the blank" problems encode the whole
                // expression in the input's aria-label/value, e.g.
                //   "x begin superscript 2 end superscript + 8x + empty input box"
                // Keep that expression text, but normalize the blank to "__".
                clone.querySelectorAll('[id^="ansed_input_"]').forEach((n) => {
                    const raw = (
                        n.getAttribute('aria-label')
                        || n.getAttribute('value')
                        || n.value
                        || n.textContent
                        || ''
                    );
                    let t = String(raw)
                        .replace(/\bempty\s+input\s+box\b/ig, '__')
                        .replace(/\s+/g, ' ')
                        .trim();
                    if (!t) t = '__';
                    const ph = document.createElement('span');
                    ph.textContent = ` ${t} `;
                    n.replaceWith(ph);
                });

                // Remove editor chrome (palette/buttons/canvas) that is not
                // part of the actual question text.
                clone.querySelectorAll('.ansed_tree, [id^="ansed_root_"] canvas').forEach(
                    n => n.remove()
                );

                // Remove any leftover canvas artifacts from formula widgets.
                clone.querySelectorAll('canvas').forEach(n => n.remove());
                // Remove script/style nodes
                clone.querySelectorAll('script, style').forEach(n => n.remove());

                // Prefer .innerText (respects CSS visibility) but fall
                // back to textContent if innerText is empty.
                let text = (clone.innerText || clone.textContent || "").trim();
                // Collapse whitespace
                text = text.replace(/\\s+/g, ' ').trim();
                return text;
            }
            """
            def _merge_editor_equation(base_text: str) -> str:
                """
                Some ALEKS templates store the full equation in hidden Ansed
                input values (e.g. "begin fraction ... empty input box ...").
                If visible prompt text is generic, append that equation string.
                """
                try:
                    raw = frame.evaluate(
                        """() => {
                            const nodes = Array.from(document.querySelectorAll(
                                '[id^="ansed_input_"], .ansed_input, input.ansed_input, textarea.ansed_input'
                            ));
                            const vals = [];
                            for (const n of nodes) {
                                const t = String(
                                    n.getAttribute('value')
                                    || n.value
                                    || n.getAttribute('aria-label')
                                    || n.textContent
                                    || ''
                                ).replace(/\s+/g, ' ').trim();
                                if (!t) continue;
                                if (/^answer\s+editor$/i.test(t)) continue;
                                vals.push(t);
                            }
                            if (!vals.length) return '';
                            // Prefer entries that look like an equation/expression.
                            vals.sort((a, b) => {
                                const sa = /begin\s+fraction|=|over|empty\s+input\s+box|\//i.test(a) ? 1 : 0;
                                const sb = /begin\s+fraction|=|over|empty\s+input\s+box|\//i.test(b) ? 1 : 0;
                                if (sa !== sb) return sb - sa;
                                return b.length - a.length;
                            });
                            return vals[0] || '';
                        }"""
                    )
                except Exception:
                    raw = ""

                base = (base_text or "").strip()
                extra = (raw or "").strip()
                if not extra:
                    return base
                if extra.lower() in base.lower():
                    return base

                # If base already has explicit equation text, keep it.
                has_equation = bool(re.search(r"=|/|\b__\b", base))
                looks_math = bool(re.search(r"begin\s+fraction|=|over|empty\s+input\s+box|/", extra, re.I))
                if not has_equation and looks_math:
                    return f"{base} {extra}".strip()
                return base

            text = frame.evaluate(js, root)
            merged = _merge_editor_equation((text or "").strip())
            cleaned = _normalize_math_speech(merged)
            cleaned = re.sub(r"(?i)\banswer\s+editor\b", " ", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned and not _is_placeholder_question(cleaned):
                return cleaned

            # Fallback: just grab text from #algoPrompt directly. Some
            # "fill-in-the-blank" problems (e.g. "Fill in the blank to
            # make w^2 - 8w + __ a perfect square") render the math
            # inline with the input box, and our container-climb heuristic
            # returns a sub-element that strips out the prompt text.
            try:
                prompt_text = frame.evaluate(
                    """() => {
                        const el = document.querySelector('#algoPrompt, #main_algo_body, .statement_block_aleks, .problem_panel');
                        if (!el) return '';
                        const clone = el.cloneNode(true);
                        clone.querySelectorAll('[aria-hidden="true"], script, style').forEach(n => n.remove());
                        clone.querySelectorAll('[id^="ansed_input_"]').forEach((n) => {
                            const raw = (
                                n.getAttribute('aria-label')
                                || n.getAttribute('value')
                                || n.value
                                || n.textContent
                                || ''
                            );
                            let t = String(raw)
                                .replace(/\bempty\s+input\s+box\b/ig, '__')
                                .replace(/\s+/g, ' ')
                                .trim();
                            if (!t) t = '__';
                            const ph = document.createElement('span');
                            ph.textContent = ` ${t} `;
                            n.replaceWith(ph);
                        });
                        clone.querySelectorAll('.ansed_tree, [id^="ansed_root_"] canvas').forEach(n => n.remove());
                        let t = (clone.innerText || clone.textContent || '').trim();
                        return t.replace(/\\s+/g, ' ').trim();
                    }"""
                )
                if prompt_text:
                    merged2 = _merge_editor_equation(prompt_text.strip())
                    cleaned2 = _normalize_math_speech(merged2)
                    cleaned2 = re.sub(r"(?i)\banswer\s+editor\b", " ", cleaned2)
                    cleaned2 = re.sub(r"\s+", " ", cleaned2).strip()
                    if cleaned2 and not _is_placeholder_question(cleaned2):
                        return cleaned2
            except Exception:
                pass
            return ""
        except Exception as exc:
            log.warning(f"Could not read question: {exc}")
            return ""

    # ─── Answer input ───────────────────────────────────────────

    def input_answer(self, answer: str) -> bool:
        """
        Type the answer into the first visible ansed_input.

        Multi-part answers (e.g. x= __, y= __) are handled by tabbing
        between the inputs and typing each comma-separated component.

        Returns True if at least one input/widget was filled, False if
        no answer widget was reachable (caller should not click Check).
        """
        answer = (answer or "").strip()
        log.info(f"  Typing answer: {answer[:80]}")

        # Some ALEKS templates use a dedicated "No solution" palette tile
        # and keep the input box disabled. For these, clicking the tile is
        # the only valid way to answer.
        if _is_no_solution_answer(answer):
            if self._click_no_solution_button():
                log.info("    selected 'No solution' tile")
                return True
            log.warning("  Model returned no-solution, but tile was not found.")
            return False

        # Number-line / inequality answers
        if answer.startswith("{") and '"numberline"' in answer:
            try:
                spec = json.loads(answer)
            except json.JSONDecodeError as exc:
                log.warning(f"  Bad numberline JSON: {exc}")
                return False
            self._solve_numberline(spec)
            # Some ALEKS problems combine the number-line graph with a
            # second "write the set in interval notation" input.
            interval = spec.get("interval")
            if interval:
                self._type_interval(str(interval))
            return True

        # Fallback for number-line tasks when the model returned plain
        # interval text (e.g. "(-4,5)") instead of the requested JSON.
        # If a figed widget is present, derive a plotting spec from the
        # interval and graph it before typing the interval notation box.
        _, figed = self._figed_root()
        if figed is not None:
            interval_text = _extract_interval_from_answer(answer)
            spec = _interval_to_numberline_spec(interval_text) if interval_text else None
            if spec is not None:
                log.info(f"  Numberline fallback from interval: {interval_text}")
                self._solve_numberline(spec)
                # Mixed templates also ask for interval notation on the right.
                self._type_interval(interval_text)
                return True

        # Graph answers (2-D coordinate plane) — not yet implemented
        if answer.startswith("{") and '"graph"' in answer:
            log.warning("  2-D graph answers are not yet fully automated — skipping.")
            return False

        frame, _ = self._problem_root()
        if frame is None:
            # The DOM may still be settling after a page transition.
            # Poll briefly for the ansed root to appear before giving up.
            deadline = time.time() + 3.0
            while time.time() < deadline and frame is None:
                time.sleep(0.2)
                frame, _ = self._problem_root()

        if frame is None:
            log.warning("  No problem frame visible — can't input.")
            self.screenshot("no_problem_frame")
            return False

        inputs = frame.query_selector_all(config.SELECTORS["ansed_input"])
        visible_inputs = [i for i in inputs if _is_visible(i)]

        # Same poll for the visible inputs themselves.
        if not visible_inputs:
            deadline = time.time() + 2.0
            while time.time() < deadline and not visible_inputs:
                time.sleep(0.2)
                inputs = frame.query_selector_all(config.SELECTORS["ansed_input"])
                visible_inputs = [i for i in inputs if _is_visible(i)]

        if not visible_inputs:
            log.warning("  No ansed_input fields visible.")
            self.screenshot("no_input_field")
            return False

        # Only split on commas when there are multiple input slots (e.g.
        # "x=__, y=__"). Single-input problems like "v^2=36 → v=-6,6"
        # want the whole string typed into the one box verbatim.
        if "," in answer and len(visible_inputs) > 1:
            parts = [p.strip() for p in answer.split(",")]
        else:
            parts = [answer]

        filled = False
        slot_count = len(visible_inputs)
        reset_done: set[str] = set()
        did_global_reset = False
        for i in range(slot_count):
            if i >= len(parts):
                # Don't force-fill extra sub-slots with the last answer
                # component (can corrupt template-style inputs).
                continue
            value = parts[i]
            try:
                # Re-acquire inputs each time: ALEKS often re-renders the
                # widget after reset, invalidating old element handles.
                current_inputs = frame.query_selector_all(config.SELECTORS["ansed_input"])
                current_visible = [el for el in current_inputs if _is_visible(el) and _is_enabled(el)]
                if not current_visible:
                    log.warning("    no enabled input slots available")
                    continue
                inp = current_visible[i] if i < len(current_visible) else current_visible[-1]

                inp.click()
                time.sleep(0.1)
                # `.fill("")` is a no-op on the ALEKS math widget — it's a
                # custom editor, not a native <input>. Click the widget's
                # own Reset button to clear prior content, then re-focus.
                # Reset only once per owning ansed widget; otherwise the
                # second slot can clear what we typed into the first slot.
                owner = self._ansed_owner_suffix(inp) or "__global__"
                if owner not in reset_done:
                    did_local_reset = self._reset_ansed_for(inp)
                    # Fallback to global reset only once for the entire
                    # question; never do this on later slots because it can
                    # wipe previously typed answers.
                    if not did_local_reset and not did_global_reset:
                        self._reset_ansed()
                        did_global_reset = True
                    reset_done.add(owner)
                try:
                    inp.click()
                    time.sleep(0.1)
                except Exception:
                    pass
                self._type_math(inp, value)
                log.info(f"    input #{i+1}: {value!r}")
                filled = True
            except Exception as exc:
                log.warning(f"    input #{i+1} failed: {exc}")
        return filled

    def _type_math(self, element, text: str):
        """
        Type an expression into an ALEKS math input, respecting its
        template-box behavior.

        ALEKS's math input uses positioned boxes for exponents, fractions
        and radicals. After entering such a box you have to press
        ArrowRight to move the cursor back out, otherwise subsequent
        characters stay inside the box.

        Handles:
          * ``^``         — exponent (typed directly, then ArrowRight out)
          * ``/``         — fraction (typed directly, then ArrowRight out
                            after the denominator)
          * ``sqrt(...)`` — clicks the palette square-root button, types
                            the radicand, then ArrowRight out
          * ``{ ... }``   — LaTeX-style grouping is stripped
        """
        # Drop any leading "x =", "y =", etc. — ALEKS wants just the
        # right-hand side of an EQUATION. Inequalities ("x<=4", "x>3")
        # don't match because they have <, >, ≤, ≥ after the variable,
        # not =, so they're left intact.
        text = re.sub(r"^\s*[a-zA-Z]\s*=\s*", "", text)

        # If the whole answer is one top-level fraction, force ALEKS's
        # fraction template (numerator/denominator slots). This avoids the
        # common mis-entry "a - b/c" when ALEKS requires a single fraction.
        top = _split_top_level_fraction(text)
        if top and self._click_fraction_button():
            num, den = top
            self._type_math(element, num)
            try:
                element.press("Tab")
            except Exception:
                pass
            self._type_math(element, den)
            element.press("ArrowRight")
            return

        i = 0
        n = len(text)
        while i < n:
            # Skip LaTeX grouping braces
            if text[i] in "{}":
                i += 1
                continue

            # Square root: sqrt(...)
            if text[i:i + 5].lower() == "sqrt(":
                depth = 1
                j = i + 5
                while j < n and depth > 0:
                    if text[j] == "(":
                        depth += 1
                    elif text[j] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                payload = text[i + 5:j]
                i = j + 1  # past the ')'
                if self._click_sqrt_button():
                    self._type_math(element, payload)
                    element.press("ArrowRight")
                else:
                    log.warning("  Couldn't find sqrt palette button; typing 'sqrt(...)' literally.")
                    element.type(f"sqrt({payload})", delay=40)
                continue

            # N-th root: root(n, x)  or  cbrt(x)
            lower = text[i:i + 5].lower()
            if lower == "root(" or text[i:i + 5].lower() == "cbrt(":
                is_cbrt = lower.startswith("cbrt")
                prefix_len = 5
                # Find matching close paren
                depth = 1
                j = i + prefix_len
                while j < n and depth > 0:
                    if text[j] == "(":
                        depth += 1
                    elif text[j] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                inside = text[i + prefix_len:j]
                i = j + 1

                if is_cbrt:
                    index_str, radicand = "3", inside
                else:
                    # Split on top-level comma
                    depth2, k = 0, 0
                    while k < len(inside):
                        c = inside[k]
                        if c == "(":
                            depth2 += 1
                        elif c == ")":
                            depth2 -= 1
                        elif c == "," and depth2 == 0:
                            break
                        k += 1
                    index_str = inside[:k].strip()
                    radicand  = inside[k + 1:].strip() if k < len(inside) else ""

                if self._click_nth_root_button():
                    # ALEKS places cursor in the index box first.
                    self._type_math(element, index_str)
                    element.press("Tab")
                    self._type_math(element, radicand)
                    element.press("ArrowRight")
                elif self._click_sqrt_button() and index_str == "2":
                    self._type_math(element, radicand)
                    element.press("ArrowRight")
                else:
                    # No n-th-root button available on this ALEKS skin.
                    # For power-of-two indices, nested square roots are
                    # equivalent and are accepted as radical expressions:
                    #   root(4,a) -> sqrt(sqrt(a))
                    k = _power_of_two_exponent(index_str)
                    if k is not None:
                        expr = radicand
                        for _ in range(k):
                            expr = f"sqrt({expr})"
                        self._type_math(element, expr)
                    else:
                        log.warning("  Couldn't find n-th-root palette button; typing literally.")
                        element.type(f"root({index_str},{radicand})", delay=40)
                continue

            # Exponent (^) and fraction (/) share the same "enter a
            # template box, type the payload, then ArrowRight out" pattern.
            if text[i] in "^/":
                element.type(text[i], delay=40)
                i += 1
                payload, i = self._grab_template_payload(text, i, n)
                if payload:
                    self._type_math(element, payload)
                element.press("ArrowRight")
                continue

            # Inequality operators. The ALEKS answer-editor does NOT
            # accept "<=" / ">=" via keyboard — the "=" key is dropped
            # after "<" or ">". Click the palette button instead.
            two = text[i:i + 2]
            if two in ("<=", ">="):
                if self._click_inequality_button(two):
                    i += 2
                    continue
                # fallback: type both chars literally
                element.type(two, delay=40)
                i += 2
                continue

            element.type(text[i], delay=40)
            i += 1

    @staticmethod
    def _grab_template_payload(text: str, i: int, n: int):
        """
        After a ^ or / trigger, read the next token that goes inside the
        template box and return ``(payload, new_index)``.

        Handles:
          * ``{...}`` — LaTeX-style grouping (unwrapped)
          * ``(...)`` — parenthesised expression (unwrapped)
          * signed numbers, single variables
        """
        if i >= n:
            return "", i

        opener = text[i]
        if opener in "{(":
            closer = "}" if opener == "{" else ")"
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if text[j] == opener:
                    depth += 1
                elif text[j] == closer:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            return text[i + 1:j], j + 1

        j = i
        if text[j] == "-":
            j += 1
        while j < n and (text[j].isdigit() or text[j] == "."):
            j += 1
        if j == i and j < n and text[j].isalpha():
            j += 1
        return text[i:j], j

    # Candidate selectors for ALEKS palette buttons. ALEKS doesn't use
    # consistent IDs across problem types, so we try multiple heuristics
    # and fall back to literal typing if none match.
    _SQRT_SELECTORS = [
        '[id*="menubar_"][id$="_ansed_sqrt"]',
        '[id*="menubar_"][id$="_ansed_squareroot"]',
        '[id*="menubar_"][id$="_ansed_radical"]',
        'button[aria-label="Square root" i]',
        'button[aria-label*="square root" i]',
        'button[aria-label*="radical" i]',
        'button[title*="square root" i]',
        'button[title*="radical" i]',
        '[role="button"][aria-label*="square root" i]',
        'button[id*="sqrt" i]',
        'button[class*="sqrt" i]',
    ]

    _FRACTION_SELECTORS = [
        '[id*="menubar_"][id$="_ansed_div"]',
        '[id*="_ansed_div"]',
        'button[aria-label*="fraction" i]',
        'button[title*="fraction" i]',
        '[role="button"][aria-label*="fraction" i]',
        'button[id*="fraction" i]',
    ]

    def _click_fraction_button(self) -> bool:
        """Click the fraction palette button in ALEKS answer editor."""
        for frame in [self.page, *self.page.frames]:
            for sel in self._FRACTION_SELECTORS:
                try:
                    el = frame.query_selector(sel)
                    if el and _is_visible(el):
                        el.click()
                        time.sleep(0.15)
                        return True
                except Exception:
                    continue
        return False

    def _click_sqrt_button(self) -> bool:
        """Click the square-root button in the ALEKS answer-editor palette."""
        for frame in [self.page, *self.page.frames]:
            for sel in self._SQRT_SELECTORS:
                try:
                    el = frame.query_selector(sel)
                    if el and _is_visible(el):
                        el.click()
                        time.sleep(0.15)
                        return True
                except Exception:
                    continue
        return False

    _NTH_ROOT_SELECTORS = [
        '[id*="menubar_"][id$="_ansed_nthroot"]',
        '[id*="menubar_"][id$="_ansed_root"]',
        '[id*="menubar_"][id$="_ansed_radicalindex"]',
        'button[aria-label*="nth root" i]',
        'button[aria-label*="n-th root" i]',
        'button[aria-label*="cube root" i]',
        'button[aria-label*="radical with index" i]',
        'button[title*="nth root" i]',
        'button[title*="n-th root" i]',
        'button[title*="cube root" i]',
        '[id*="nthroot" i]',
        '[id*="nth_root" i]',
    ]

    def _click_nth_root_button(self) -> bool:
        """Click the n-th-root palette button (the one with a small index)."""
        for frame in [self.page, *self.page.frames]:
            for sel in self._NTH_ROOT_SELECTORS:
                try:
                    el = frame.query_selector(sel)
                    if el and _is_visible(el):
                        el.click()
                        time.sleep(0.15)
                        return True
                except Exception:
                    continue

            # Fallback for ALEKS skins that expose toolbar tiles as generic
            # menubar nodes without semantic ids/aria labels.
            try:
                ops = []
                for el in frame.query_selector_all('[id^="menubar_"]'):
                    eid = (el.get_attribute("id") or "").lower()
                    if not eid or not _is_visible(el):
                        continue
                    if "_ansed" not in eid:
                        continue
                    if eid.endswith("_ansed"):
                        continue
                    if any(tok in eid for tok in (
                        "reset", "undo", "interval", "pair", "emptyset",
                        "infinity", "neginfinity", "figed", "lineopen",
                        "lineclose", "lineinterval", "eraser",
                    )):
                        continue
                    ops.append((eid, el))

                # Prefer ids hinting at a root/radical tool.
                for eid, el in ops:
                    if "root" in eid or "rad" in eid:
                        el.click()
                        time.sleep(0.15)
                        return True

                # Common ALEKS layout: [sqrt, nth-root, ...]
                if len(ops) >= 2:
                    ops[1][1].click()
                    time.sleep(0.15)
                    return True
            except Exception:
                pass
        return False

    # Inequality palette buttons. ALEKS strict `<` and `>` work via
    # keyboard, but `<=` / `>=` need a palette click because typing `=`
    # after a relation key is dropped by the math editor.
    _INEQUALITY_SELECTORS = {
        "<=": [
            '[id*="menubar_"][id$="_ansed_le"]',
            '[id*="menubar_"][id$="_ansed_leq"]',
            '[id*="menubar_"][id$="_ansed_lessequal"]',
            'button[aria-label*="less than or equal" i]',
            'button[title*="less than or equal" i]',
        ],
        ">=": [
            '[id*="menubar_"][id$="_ansed_ge"]',
            '[id*="menubar_"][id$="_ansed_geq"]',
            '[id*="menubar_"][id$="_ansed_greaterequal"]',
            'button[aria-label*="greater than or equal" i]',
            'button[title*="greater than or equal" i]',
        ],
    }

    def _click_inequality_button(self, op: str) -> bool:
        """Click the ≤ or ≥ button in the ALEKS inequality palette."""
        for frame in [self.page, *self.page.frames]:
            for sel in self._INEQUALITY_SELECTORS.get(op, []):
                try:
                    el = frame.query_selector(sel)
                    if el and _is_visible(el):
                        el.click()
                        time.sleep(0.15)
                        return True
                except Exception:
                    continue
        return False

    def _click_no_solution_button(self) -> bool:
        """Click the ALEKS 'No solution' palette tile if visible."""
        selectors = [
            '[id*="_ansed_nosolution" i]',
            '[id*="nosolution" i]',
            'button[aria-label*="no solution" i]',
            '[role="button"][aria-label*="no solution" i]',
            'button[title*="no solution" i]',
        ]
        for frame in [self.page, *self.page.frames]:
            for sel in selectors:
                try:
                    el = frame.query_selector(sel)
                    if el and _is_visible(el):
                        el.click()
                        time.sleep(0.15)
                        return True
                except Exception:
                    continue

            # Text fallback for skins where the tile is a generic div.
            script = r"""
                () => {
                    const cands = Array.from(document.querySelectorAll('button, [role=button], div, span'));
                    for (const el of cands) {
                        const txt = ((el.innerText || el.textContent || '') + '').trim().toLowerCase();
                        if (!txt) continue;
                        if (!/no\s*solution/.test(txt)) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width < 2 || r.height < 2) continue;
                        const cs = getComputedStyle(el);
                        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
                        el.click();
                        return true;
                    }
                    return false;
                }
            """
            try:
                if frame.evaluate(script):
                    time.sleep(0.15)
                    return True
            except Exception:
                continue
        return False

    # ─── Interval-notation input ────────────────────────────────

    # ALEKS palette button IDs for interval notation (stable across
    # problems — only the "undefined_N" suffix varies). We match with
    # a CSS attribute-contains selector so any instance number works.
    #
    # Confirmed from recordings/20260421-191121/snapshots (Apr 2026):
    #
    #   menubar_undefined_1_ansed_pair        → (  ,  )
    #   menubar_undefined_1_ansed_interval    → [  ,  ]
    #   menubar_undefined_1_ansed_intervalOC  → (  ,  ]
    #   menubar_undefined_1_ansed_intervalCO  → [  ,  )
    #   menubar_undefined_1_ansed_emptyset    → ∅
    #   menubar_undefined_1_ansed_infinity    → +∞
    #   menubar_undefined_1_ansed_neginfinity → −∞
    _INTERVAL_PALETTE = {
        ("(", ")"): "[id*='ansed_pair']",
        ("[", "]"): "[id*='ansed_interval']:not([id*='ansed_intervalOC']):not([id*='ansed_intervalCO'])",
        ("(", "]"): "[id*='ansed_intervalOC']",
        ("[", ")"): "[id*='ansed_intervalCO']",
        "empty":    "[id*='ansed_emptyset']",
        "+inf":     "[id*='ansed_infinity']:not([id*='neginfinity'])",
        "-inf":     "[id*='ansed_neginfinity']",
    }

    def _type_interval(self, interval: str) -> bool:
        """
        Type an interval-notation answer using the ALEKS palette buttons.

        ``interval`` accepts forms like:
          "[-5,-2]"              (inclusive)
          "(-3,2)"               (open)
          "(-5,-1]"              (mixed)
          "(-inf,-3)U(2,+inf)"   (disjoint union)
          "empty"                (empty set)
          "[3,+inf)"             (ray)
        """
        if not interval:
            return False

        frame, _ = self._problem_root()
        if frame is None:
            log.warning("  No ansed editor visible for interval notation.")
            return False

        inputs = [i for i in frame.query_selector_all(config.SELECTORS["ansed_input"])
                  if _is_visible(i)]
        if not inputs:
            log.warning("  No visible interval input — skipping.")
            return False
        inp = inputs[-1]
        try:
            inp.click()
        except Exception:
            pass

        # ALEKS's interval editor is a custom widget; .fill('') does nothing.
        # Use the palette's circular-arrow Reset button to clear prior state,
        # then re-focus the input (reset steals focus).
        self._reset_ansed()
        try:
            inp.click()
            time.sleep(0.15)
        except Exception:
            pass

        log.info(f"  Typing interval: {interval}")

        pieces = re.split(r"\s*[Uu∪]\s*", interval.strip())
        for pi, piece in enumerate(pieces):
            piece = piece.strip()
            if pi > 0:
                # Union between pieces — ALEKS typically accepts typing 'U'
                # directly at the top level of the interval editor.
                try:
                    inp.type("U", delay=40)
                except Exception:
                    pass

            if piece.lower() in ("empty", "∅", "{}", "null"):
                if self._click_interval_palette("empty"):
                    log.info("    clicked ∅")
                else:
                    log.warning("  Couldn't click ∅ palette button.")
                continue

            m = re.match(r"^\s*([\[(])\s*(.+?)\s*,\s*(.+?)\s*([\])])\s*$", piece)
            if not m:
                log.warning(f"  Couldn't parse interval piece {piece!r} — typing literally.")
                try:
                    inp.type(piece, delay=40)
                except Exception:
                    pass
                continue

            ob, a_raw, b_raw, cb = m.groups()
            # Strip whitespace — otherwise ALEKS treats space as a slot advance
            a_raw = a_raw.strip()
            b_raw = b_raw.strip()
            if not self._click_interval_palette((ob, cb)):
                log.warning(f"  Couldn't click bracket template {ob}…{cb}; typing literally.")
                try:
                    inp.type(f"{ob}{a_raw},{b_raw}{cb}", delay=40)
                except Exception:
                    pass
                continue
            log.info(f"    clicked {ob}□,□{cb} template; filling {a_raw!r}, {b_raw!r}")

            # After the template click the cursor sits in the left slot.
            self._type_interval_value(inp, a_raw)
            # Tab advances between slots of the interval template. Using a
            # literal ',' risks spawning an extra slot in some ALEKS layouts.
            try:
                inp.press("Tab")
            except Exception:
                pass
            self._type_interval_value(inp, b_raw)
            # Exit the template
            try:
                inp.press("ArrowRight")
            except Exception:
                pass

        return True

    def _type_interval_value(self, inp, value: str):
        """Type a single endpoint value into the currently-focused slot."""
        v = value.strip().lower().replace(" ", "")
        if v in ("+inf", "inf", "infinity", "+infinity"):
            if self._click_interval_palette("+inf"):
                return
        if v in ("-inf", "-infinity"):
            if self._click_interval_palette("-inf"):
                return
        try:
            self._type_math(inp, value)
        except Exception as exc:
            log.warning(f"  Couldn't type interval value {value!r}: {exc}")

    def _click_interval_palette(self, key) -> bool:
        """Click the palette button for ``key`` (see ``_INTERVAL_PALETTE``)."""
        sel = self._INTERVAL_PALETTE.get(key)
        if not sel:
            return False
        for frame in [self.page, *self.page.frames]:
            try:
                el = frame.query_selector(sel)
                if el and _is_visible(el):
                    el.click()
                    time.sleep(0.2)
                    return True
            except Exception:
                continue
        return False

    def _reset_ansed(self) -> bool:
        """Click the interval editor's Reset (circular-arrow) button."""
        return self._click_first_visible(
            config.SELECTORS["ansed_reset"], "Ansed reset"
        )

    def _reset_ansed_for(self, inp) -> bool:
        """
        Click the Reset button belonging to the ansed widget that owns
        ``inp``. Multi-part problems (e.g. 216^(1/3)=__, 16^(1/4)=__)
        render two separate ansed widgets side-by-side, each with its
        own palette — we need the reset that matches THIS input.

        Strategy: walk up the DOM from the input to find the nearest
        ancestor whose id starts with "ansed_root_", extract its suffix
        (e.g. "formed_innerEditor_0_formed_1"), and look for a reset
        button whose id contains that suffix. Fall back to the global
        reset if we can't correlate.
        """
        suffix = self._ansed_owner_suffix(inp)

        if suffix:
            # Two common ID shapes:
            #   menubar_<suffix>_ansed_reset       (single-widget forms)
            #   menubar_<suffix>_<N>_ansed_reset   (multi-widget forms)
            for sel in (
                f"[id*='{suffix}'][id$='_ansed_reset']",
                f"button[id*='{suffix}'][id*='reset' i]",
            ):
                if self._click_first_visible(sel, f"Ansed reset ({suffix[:30]})"):
                    return True
        return False

    def _ansed_owner_suffix(self, inp) -> str:
        """Return owning ansed_root_* suffix for an input, else empty string."""
        try:
            return inp.evaluate(
                """el => {
                    let n = el;
                    while (n && n !== document.body) {
                        const id = n.id || '';
                        if (id.startsWith('ansed_root_')) {
                            return id.slice('ansed_root_'.length);
                        }
                        n = n.parentElement;
                    }
                    return '';
                }"""
            ) or ""
        except Exception:
            return ""

    def _reset_figed(self) -> bool:
        """Click the number-line editor's Reset (circular-arrow) button."""
        return self._click_first_visible(
            config.SELECTORS["figed_reset"], "Figed reset"
        )


    def _solve_numberline(self, spec: dict):
        """
        Plot a compound inequality on the ALEKS number-line editor.

        Expected ``spec`` shape::

            {
              "type":     "numberline",
              "points":   [{"x": -1, "open": true}, {"x": 7, "open": true}],
              "segments": [{"from": -1, "to": 7}]
            }

        ``from``/``to`` may be the string ``"+inf"`` or ``"-inf"`` for
        rays. The number line's x-range is read from the ALEKS editor's
        accessibility label (e.g. "x-values range from − 10 to 10").
        """
        # Locate the editor in any frame and learn its pixel/value mapping
        root, surface, bbox, xmin, xmax = self._find_numberline(spec)
        if root is None:
            log.warning("  No number-line editor found — skipping.")
            return

        # Clear any leftover marks from a previous (wrong) attempt.
        self._reset_figed()

        log.info(f"  Number line: x ∈ [{xmin}, {xmax}], bbox={bbox}")

        # Tick labels sit ~mid-height; the clickable axis is just above.
        mid_y = bbox["y"] + bbox["height"] * 0.55
        # Leave a small margin so clicks stay inside the drawable area.
        margin_px = max(12.0, bbox["width"] * 0.035)
        left_px   = bbox["x"] + margin_px
        right_px  = bbox["x"] + bbox["width"] - margin_px
        usable_w  = right_px - left_px

        def x_to_px(x) -> float:
            if x == "+inf" or x == float("inf"):
                return right_px
            if x == "-inf" or x == float("-inf"):
                return left_px
            x = float(x)
            x = max(xmin, min(xmax, x))
            frac = (x - xmin) / (xmax - xmin) if xmax != xmin else 0.5
            return left_px + frac * usable_w

        # 1. Draw each endpoint (open or closed dot)
        for pt in spec.get("points", []):
            tool = "figed_open" if pt.get("open") else "figed_closed"
            if not self._click_figed_tool(tool):
                log.warning(f"  Couldn't select {tool} tool.")
                continue
            px = x_to_px(pt.get("x"))
            self.page.mouse.click(px, mid_y)
            time.sleep(0.25)
            log.info(f"    • {'open' if pt.get('open') else 'closed'} dot at x={pt.get('x')}")

        # 2. Draw each interval/ray (click two endpoints with the line tool)
        for seg in spec.get("segments", []):
            if not self._click_figed_tool("figed_interval"):
                log.warning("  Couldn't select interval tool.")
                continue
            fx = x_to_px(seg.get("from"))
            tx = x_to_px(seg.get("to"))
            self.page.mouse.click(fx, mid_y)
            time.sleep(0.25)
            self.page.mouse.click(tx, mid_y)
            time.sleep(0.25)
            log.info(f"    — segment from {seg.get('from')} to {seg.get('to')}")

        # 3. Eraser cleanup. ALEKS's interval tool paints *rays* that extend
        #    outward from each click, so drawing a bounded segment [a,b] also
        #    produces unwanted rays (-inf, a) and (b, +inf). Erase them by
        #    clicking anywhere inside those outside regions. For rays that
        #    the user actually wanted (segment going to ±inf), we skip the
        #    corresponding cleanup.
        segments = spec.get("segments", [])
        if segments:
            # Union bounds: smallest `from` and largest `to` across segments.
            def _as_num(v, default):
                if v == "+inf":  return float("inf")
                if v == "-inf":  return float("-inf")
                try:             return float(v)
                except Exception: return default
            left_bound  = min(_as_num(s.get("from"), xmax) for s in segments)
            right_bound = max(_as_num(s.get("to"),   xmin) for s in segments)

            cleanups = []
            if left_bound != float("-inf") and left_bound > xmin + 0.001:
                cleanups.append(("left",  left_px + 2))
            if right_bound != float("+inf") and right_bound < xmax - 0.001:
                cleanups.append(("right", right_px - 2))

            if cleanups and self._click_figed_tool("figed_eraser"):
                for side, px in cleanups:
                    self.page.mouse.click(px, mid_y)
                    time.sleep(0.25)
                    log.info(f"    ✂ erased {side} ray")

    def _find_numberline(self, spec: dict):
        """
        Locate the number-line editor across all frames and return
        ``(root_handle, surface_handle, bbox_dict, xmin, xmax)``.
        """
        import re as _re
        for frame in [self.page, *self.page.frames]:
            try:
                root = frame.query_selector(config.SELECTORS["figed_root"])
                if not root or not _is_visible(root):
                    continue
            except Exception:
                continue

            # Parse "x-values range from - 10 to 10" from the aria label
            xmin, xmax = -10.0, 10.0
            try:
                label = frame.query_selector(config.SELECTORS["figed_label"])
                if label:
                    txt = (label.inner_text() or "").replace("−", "-").replace("–", "-")
                    m = _re.search(r"from\s*(-?\d+(?:\.\d+)?)\s*to\s*(-?\d+(?:\.\d+)?)", txt)
                    if m:
                        xmin, xmax = float(m.group(1)), float(m.group(2))
            except Exception:
                pass

            # Allow the LLM to override if it included a range
            if "xmin" in spec and "xmax" in spec:
                try:
                    xmin, xmax = float(spec["xmin"]), float(spec["xmax"])
                except Exception:
                    pass

            surface = None
            try:
                surface = frame.query_selector(config.SELECTORS["figed_surface"])
            except Exception:
                pass

            target = surface if (surface and _is_visible(surface)) else root
            try:
                bbox = target.bounding_box()
            except Exception:
                bbox = None
            if not bbox:
                continue
            return root, surface, bbox, xmin, xmax

        return None, None, None, -10.0, 10.0

    def _click_figed_tool(self, selector_key: str) -> bool:
        """Click a toolbar button in the figure editor (open/closed/interval/eraser)."""
        selector = config.SELECTORS[selector_key]
        for frame in [self.page, *self.page.frames]:
            try:
                el = frame.query_selector(selector)
                if el and _is_visible(el):
                    el.click()
                    time.sleep(0.2)
                    return True
            except Exception:
                continue
        return False

    # ─── Submit / advance ───────────────────────────────────────

    def _click_first_visible(self, selector: str, description: str) -> bool:
        """Click the first visible element matching selector in page or any frame."""
        for frame in [self.page, *self.page.frames]:
            try:
                el = frame.query_selector(selector)
                if el and _is_visible(el):
                    el.click()
                    log.info(f"  Clicked {description}")
                    return True
            except Exception:
                continue
        return False

    def check_answer(self) -> bool:
        """Click the ALEKS 'Check' button."""
        self.last_notice = None
        ok = self._click_first_visible(
            config.SELECTORS["check_answer"], "Check Answer"
        )
        if ok:
            time.sleep(config.WAIT_AFTER_CHECK_SECONDS)
            # Mid-answer ALEKS sometimes throws up a small informational
            # dialog (e.g. "Be Careful — Fill in all the empty boxes.").
            # Dismiss it so the retry loop can see the real result.
            self.last_notice = self.dismiss_notice()
        return ok

    def dismiss_notice(self) -> str | None:
        """
        Detect and dismiss an ALEKS informational popup (e.g. "Be Careful",
        "Note", "Warning") by clicking its OK button. Returns the message
        text if one was dismissed, else None.
        """
        script = r"""
            () => {
                const texts = [];
                const roots = [document, ...Array.from(document.querySelectorAll('iframe'))
                    .map(f => { try { return f.contentDocument; } catch (e) { return null; } })
                    .filter(Boolean)];

                for (const root of roots) {
                    // Find any visible button whose text is exactly 'OK' or 'Ok'
                    const btns = Array.from(root.querySelectorAll('button, input[type=button], input[type=submit], [role=button]'));
                    for (const b of btns) {
                        const label = ((b.innerText || b.value || '') + '').trim();
                        if (!/^ok$/i.test(label)) continue;
                        const rect = b.getBoundingClientRect();
                        if (rect.width < 2 || rect.height < 2) continue;
                        const style = (b.ownerDocument.defaultView || window).getComputedStyle(b);
                        if (style.visibility === 'hidden' || style.display === 'none') continue;

                        // Walk up to find the dialog container and grab its message
                        let msg = '';
                        let node = b.parentElement;
                        for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
                            const txt = (node.innerText || '').trim();
                            if (txt && txt.length > label.length + 1) {
                                msg = txt.replace(/\s*\bOK\b\s*$/i, '').trim();
                                break;
                            }
                        }
                        b.click();
                        return msg || '(notice dismissed)';
                    }
                }
                return null;
            }
        """
        for frame in [self.page, *self.page.frames]:
            try:
                msg = frame.evaluate(script)
            except Exception:
                continue
            if msg:
                log.info(f"  ⚠ ALEKS notice: {msg!r} — dismissed.")
                time.sleep(0.3)
                return msg
        return None

    def continue_after_correct(self) -> bool:
        """
        Click 'Continue' after ALEKS has confirmed a correct answer.
        Only exists when the previous Check was graded correct.
        """
        ok = self._click_first_visible(
            config.SELECTORS["next_correct"], "Continue (correct)"
        )
        if ok:
            time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
        return ok

    def skip_to_new_item(self) -> bool:
        """Request a new problem (used after an incorrect attempt)."""
        ok = self._click_first_visible(
            config.SELECTORS["new_item"], "New Item"
        )
        if ok:
            time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
        return ok

    def click_try_again(self) -> bool:
        """
        After too many wrong answers, ALEKS replaces the bottom-right button
        with a 'Try Again' action that advances to a fresh attempt/problem.
        Same ID as `continue_learning` — the label just changes.
        """
        ok = self._click_first_visible(
            config.SELECTORS["try_again"], "Try Again / Continue"
        )
        if ok:
            time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
        return ok

    def recover_from_explanation(self) -> bool:
        """
        After an incorrect answer ALEKS shows a "Let's Take a Break / Your
        answer is incorrect" screen with the CORRECT ANSWER and EXPLANATION
        inlined below the problem. The bottom-nav button on this screen is
        usually off-screen; scroll the whole page to the bottom, then click
        whichever advancement button is visible.

        Returns True if something was clicked.
        """
        # Scroll the page (and any scrollable ALEKS container) to the
        # bottom so the bottom-nav button is laid out and clickable.
        try:
            self.page.evaluate(
                "() => { window.scrollTo(0, document.body.scrollHeight); "
                "document.querySelectorAll('*').forEach(el => { "
                "  if (el.scrollHeight > el.clientHeight + 20) "
                "    el.scrollTop = el.scrollHeight; }); }"
            )
            time.sleep(0.3)
        except Exception:
            pass

        # Try every known "advance" button in priority order
        for key, desc in [
            ("try_again",        "Try Again (post-explanation)"),
            ("new_item",         "Next problem (post-explanation)"),
            ("next_correct",     "Continue (post-explanation)"),
            ("continue_learning", "Start / Continue (post-explanation)"),
        ]:
            if self._click_first_visible(config.SELECTORS[key], desc):
                time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
                return True
        return False

    def advance_past_checkpoint(self) -> bool:
        """
        After a streak of correct answers ALEKS shows a 'mastery checkpoint'
        screen with no problem visible. From the recording:

          1. URL moves from #item to #   (problem goes away)
          2. #smt_bottomnav_button_input_newItem  shows 'Continue My Path'
             → clicking navigates back to #item
          3. #smt_bottomnav_button_input_learning  shows 'Start'
             → clicking reveals the next problem

        This helper clicks whichever of those two buttons is currently
        visible and waits a moment. Returns True if something was clicked.
        """
        clicked = False
        for key, desc in [
            ("new_item",          "Continue My Path (checkpoint)"),
            ("continue_learning", "Start (checkpoint)"),
        ]:
            if self._click_first_visible(config.SELECTORS[key], desc):
                clicked = True
                time.sleep(config.WAIT_AFTER_NEXT_SECONDS)
        return clicked

    def check_result(self) -> str:
        """
        Determine what state ALEKS is in after the last 'Check' click.

        Returns:
          'correct'   — the "Next" button (learningCorrect) is visible.
          'try_again' — ALEKS gave up on this problem and offers "Try Again".
          'incorrect' — a secondary "Explain" button is visible (still same
                        problem — we can submit another answer).
          'unknown'   — no definitive indicator yet.
        """
        # 1. Correct?
        for frame in [self.page, *self.page.frames]:
            try:
                el = frame.query_selector(config.SELECTORS["next_correct"])
                if el and _is_visible(el):
                    return "correct"
            except Exception:
                continue

        # 2. "Try Again" state (shown after max wrong attempts on this problem)
        for frame in [self.page, *self.page.frames]:
            try:
                el = frame.query_selector(config.SELECTORS["try_again"])
                if el and _is_visible(el):
                    try:
                        txt = (el.inner_text() or "").strip().lower()
                    except Exception:
                        txt = ""
                    # Same ID is reused for "Start" / "Continue My Path" on
                    # the dashboard; only treat it as try-again on the
                    # problem page.
                    if "try again" in txt or "continue" in txt:
                        return "try_again"
            except Exception:
                continue

        # 3. Incorrect — a secondary action (Explain / Recheck hint) shown
        for frame in [self.page, *self.page.frames]:
            try:
                el = frame.query_selector(config.SELECTORS["secondary_button"])
                if el and _is_visible(el):
                    return "incorrect"
            except Exception:
                continue

        return "unknown"


# ─── helpers ────────────────────────────────────────────────────

def _is_visible(el) -> bool:
    try:
        return bool(el.is_visible())
    except Exception:
        return False


def _is_enabled(el) -> bool:
    try:
        return bool(el.is_enabled())
    except Exception:
        return False


def _power_of_two_exponent(index_text: str) -> int | None:
    """
    If index_text is a positive power of two, return k such that
    index_text == 2**k. Otherwise return None.
    """
    try:
        n = int((index_text or "").strip())
    except Exception:
        return None
    if n <= 0 or (n & (n - 1)) != 0:
        return None
    k = 0
    while n > 1:
        n //= 2
        k += 1
    return k


def _split_top_level_fraction(text: str) -> tuple[str, str] | None:
    """
    If text is exactly one top-level fraction `NUM/DEN`, return (NUM, DEN).
    Otherwise return None.
    """
    s = (text or "").strip()
    if not s:
        return None

    # Trim one outer parenthesis pair if they wrap the whole expression.
    def strip_outer_parens(x: str) -> str:
        x = x.strip()
        if len(x) >= 2 and x[0] == "(" and x[-1] == ")":
            depth = 0
            for i, ch in enumerate(x):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if depth == 0 and i < len(x) - 1:
                    return x
            return x[1:-1].strip()
        return x

    s = strip_outer_parens(s)

    depth = 0
    slash_at = -1
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "/" and depth == 0:
            if slash_at != -1:
                return None
            slash_at = i

    if slash_at == -1:
        return None

    num = s[:slash_at].strip()
    den = s[slash_at + 1:].strip()
    if not num or not den:
        return None

    return strip_outer_parens(num), strip_outer_parens(den)


def _is_placeholder_question(text: str) -> bool:
    """True when extracted question has no real math/instruction content."""
    t = (text or "").strip()
    if not t:
        return True
    if re.fullmatch(r"[_\W]+", t):
        return True
    if re.fullmatch(r"(?i)answer\s+editor(?:\s+__)?", t):
        return True
    return False


def _is_no_solution_answer(text: str) -> bool:
    """True if model output means ALEKS 'No solution'."""
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t in {
        "no solution",
        "no solutions",
        "none",
        "no real solution",
        "no real solutions",
        "there is no solution",
        "there are no solutions",
    }


def _normalize_math_speech(text: str) -> str:
    """
    ALEKS renders math as MathJax with screen-reader speech text like
    "begin fraction 2 over 3 end fraction" or "negative 3 squared".
    The model parses plain math notation much more reliably, so convert
    speech phrases back to symbols before handing the question off.

    Examples of conversions:
      "begin fraction a over b end fraction"       -> "(a)/(b)"
      "StartFraction a Over b EndFraction"         -> "(a)/(b)"
      "a Superscript 2 Baseline"                   -> "a^(2)"
      "a squared"                                  -> "a^(2)"
      "a cubed"                                    -> "a^(3)"
      "the square root of 5"                       -> "sqrt(5)"
      "negative 2"                                 -> "-2"
      "times"                                      -> "*"
      "divided by"                                 -> "/"
    """
    if not text:
        return text

    s = text

    # Normalise unicode math symbols
    s = (s.replace("−", "-")      # U+2212 minus
           .replace("–", "-")      # en-dash
           .replace("—", "-")      # em-dash
           .replace("·", "*")
           .replace("×", "*")
           .replace("÷", "/")
           .replace("≤", "<=")
           .replace("≥", ">="))

    # Fractions — "begin fraction ... end fraction",
    # "StartFraction ... Over ... EndFraction", and nested variants.
    # Also handle generic "begin/end" brackets that ALEKS sometimes emits
    # for superscript, subscript, square root, etc.
    frac_patterns = [
        re.compile(
            r"(?i)\bbegin\s+fraction\s+(.+?)\s+over\s+(.+?)\s+end\s+fraction\b"
        ),
        re.compile(
            r"(?i)\bStartFraction\s+(.+?)\s+Over\s+(.+?)\s+EndFraction\b"
        ),
    ]
    sup_patterns = [
        re.compile(r"(?i)\bbegin\s+superscript\s+(.+?)\s+end\s+superscript\b"),
        re.compile(r"(?i)\bbegin\s+exponent\s+(.+?)\s+end\s+exponent\b"),
    ]
    sub_patterns = [
        re.compile(r"(?i)\bbegin\s+subscript\s+(.+?)\s+end\s+subscript\b"),
    ]
    sqrt_patterns = [
        re.compile(r"(?i)\bbegin\s+square\s+root\s+(.+?)\s+end\s+square\s+root\b"),
        re.compile(r"(?i)\bbegin\s+root\s+(.+?)\s+end\s+root\b"),
        re.compile(r"(?i)\bStartRoot\s+(.+?)\s+EndRoot\b"),
    ]
    abs_patterns = [
        re.compile(r"(?i)\bbegin\s+absolute\s+value\s+(.+?)\s+end\s+absolute\s+value\b"),
    ]

    # Repeatedly apply (handles nesting). Fractions first, then exponents,
    # because a fraction often contains an exponent.
    for _ in range(8):
        changed = False
        for pat in frac_patterns:
            new_s = pat.sub(lambda m: f"({m.group(1).strip()})/({m.group(2).strip()})", s)
            if new_s != s: s, changed = new_s, True
        for pat in sqrt_patterns:
            new_s = pat.sub(lambda m: f"sqrt({m.group(1).strip()})", s)
            if new_s != s: s, changed = new_s, True
        for pat in sup_patterns:
            new_s = pat.sub(lambda m: f"^({m.group(1).strip()})", s)
            if new_s != s: s, changed = new_s, True
        for pat in sub_patterns:
            new_s = pat.sub(lambda m: f"_({m.group(1).strip()})", s)
            if new_s != s: s, changed = new_s, True
        for pat in abs_patterns:
            new_s = pat.sub(lambda m: f"|{m.group(1).strip()}|", s)
            if new_s != s: s, changed = new_s, True
        if not changed:
            break

    # MathJax V3 "... Superscript X Baseline ..."  ->  "...^(X)"
    s = re.sub(
        r"(?i)\s+Superscript\s+(.+?)\s+Baseline\b",
        lambda m: f"^({m.group(1).strip()})",
        s,
    )
    # "N squared" / "N cubed"
    s = re.sub(r"(?i)\b(\w+)\s+squared\b", r"\1^(2)", s)
    s = re.sub(r"(?i)\b(\w+)\s+cubed\b",   r"\1^(3)", s)

    # Roots — "the square root of X"
    s = re.sub(r"(?i)\bthe\s+square\s+root\s+of\s+", "sqrt ", s)
    s = re.sub(r"(?i)\bsquare\s+root\s+of\s+",       "sqrt ", s)

    # Word operators
    s = re.sub(r"(?i)\bnegative\s+", "-", s)
    s = re.sub(r"(?i)\bplus\b",      "+", s)
    s = re.sub(r"(?i)\bminus\b",     "-", s)
    s = re.sub(r"(?i)\btimes\b",     "*", s)
    s = re.sub(r"(?i)\bdivided\s+by\b", "/", s)
    s = re.sub(r"(?i)\bequals\b",    "=", s)
    s = re.sub(r"(?i)\bempty\s+input\s+box\b", "__", s)

    # Tidy: collapse spaces around operators and multi-spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_interval_from_answer(answer: str) -> str:
    """
    Extract interval notation from an answer string.

    Accepts plain interval strings ("(-4,5)"), unions
    ("(-inf,-3)U(2,+inf)"), and mixed set-builder forms
    ("{x|-4<x<5}=(-4,5)").
    """
    a = (answer or "").strip()
    if not a:
        return ""

    # If the model returned "... = (...)" keep the RHS.
    if "=" in a and not a.startswith('{"'):
        a = a.split("=")[-1].strip()

    # x in (...) variants
    a = re.sub(r"(?i)^\s*[a-zA-Z]\s*(?:in|∈)\s*", "", a).strip()

    # Set-builder with chained inequalities: {x|a<x<b}
    if a.startswith("{") and "|" in a and a.endswith("}"):
        inside = a[1:-1]
        parts = inside.split("|", 1)
        cond = parts[1].strip() if len(parts) == 2 else ""
        # a < x < b / a <= x < b / a < x <= b / a <= x <= b
        m = re.match(
            r"^(.+?)\s*(<=|<)\s*[a-zA-Z]\s*(<=|<)\s*(.+?)$",
            cond,
        )
        if m:
            left, lop, rop, right = m.groups()
            ob = "(" if lop == "<" else "["
            cb = ")" if rop == "<" else "]"
            return f"{ob}{left.strip()},{right.strip()}{cb}"

    # Plain interval / union.
    if re.search(r"[\[(].+?,.+?[\])]", a):
        return a

    return ""


def _parse_numberline_bound(token: str):
    """Parse interval endpoint token to float or +/-inf markers."""
    t = (token or "").strip().replace(" ", "")
    if not t:
        return None
    tl = t.lower()
    if tl in {"+inf", "inf", "+infinity", "infinity", "+oo", "oo", "∞", "+∞"}:
        return "+inf"
    if tl in {"-inf", "-infinity", "-oo", "-∞"}:
        return "-inf"
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", t):
        try:
            return float(t)
        except Exception:
            return None
    if re.fullmatch(r"[+-]?\d+/\d+", t):
        try:
            n, d = t.split("/", 1)
            dval = float(d)
            if abs(dval) < 1e-12:
                return None
            return float(n) / dval
        except Exception:
            return None
    return None


def _interval_to_numberline_spec(interval: str) -> dict | None:
    """Convert interval notation into the numberline JSON spec used by _solve_numberline."""
    text = (interval or "").strip()
    if not text:
        return None

    if text.lower() in {"empty", "∅", "{}", "null"}:
        return {"type": "numberline", "points": [], "segments": []}

    pieces = [p.strip() for p in re.split(r"\s*[Uu∪]\s*", text) if p.strip()]
    points = []
    segments = []

    for piece in pieces:
        m = re.match(r"^\s*([\[(])\s*(.+?)\s*,\s*(.+?)\s*([\])])\s*$", piece)
        if not m:
            return None
        ob, a_raw, b_raw, cb = m.groups()
        a = _parse_numberline_bound(a_raw)
        b = _parse_numberline_bound(b_raw)
        if a is None or b is None:
            return None

        segments.append({"from": a, "to": b})
        if a not in {"-inf", "+inf"}:
            points.append({"x": a, "open": ob == "("})
        if b not in {"-inf", "+inf"}:
            points.append({"x": b, "open": cb == ")"})

    return {"type": "numberline", "points": points, "segments": segments, "interval": text}
