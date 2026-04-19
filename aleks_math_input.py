"""
aleks_math_input.py — ALEKS Math Input Layer

Automatically translates AI-returned answers into ALEKS UI operations.
Handles all 44 ALEKS input types: fractions, square roots, exponents,
mixed numbers, pi, trig functions, absolute values, inequalities, graphs.

Architecture:
  1. ALEKSInputLayer.input_answer(answer_str_or_json)
       → _focus_editor()       — click the ansed math editor
       → _clear_editor()       — backspace loop + Clear button
       → _input_expression()   — tokenize + dispatch tokens
       → _process_token()      — execute each token as UI ops

Button-click rule: after EVERY toolbar button click, call _refocus() to
restore keyboard focus to the math editor. This prevents the "empty box"
bug where toolbar clicks steal focus away from nested template boxes.
"""

import json
import logging
import re
import time

log = logging.getLogger("aleks_math_input")


# ─── Math tool button selectors ──────────────────────────────────────────────

_BUTTON_SELECTORS = {
    "fraction": [
        'button[title*="Fraction" i]',
        'button[aria-label*="Fraction" i]',
        'button[title*="Fracción" i]',
        'button[title*="fraccion" i]',
        '[class*="fraction_button"]',
        '[class*="fractionButton"]',
        'button[title="/"]',
    ],
    "sqrt": [
        'button[title*="Square root" i]',
        'button[aria-label*="Square root" i]',
        'button[title*="Raíz cuadrada" i]',
        'button[title*="raiz cuadrada" i]',
        'button[title*="Raíz" i]',
        '[class*="sqrt_button"]',
        '[class*="sqrtButton"]',
        'button:has-text("√")',
        'button[title="√"]',
    ],
    "exponent": [
        'button[title*="Exponent" i]',
        'button[aria-label*="Exponent" i]',
        'button[title*="Exponente" i]',
        '[class*="exponent_button"]',
        '[class*="exponentButton"]',
    ],
    "pi": [
        'button[title="π"]',
        'button[title*="Pi" i]',
        'button[aria-label*="Pi" i]',
        'button:has-text("π")',
        '[class*="pi_button"]',
    ],
    "absolute_value": [
        'button[title*="Absolute" i]',
        'button[aria-label*="Absolute" i]',
        'button[title*="Valor absoluto" i]',
        'button:has-text("|•|")',
    ],
    "mixed_number": [
        'button[title*="Mixed" i]',
        'button[aria-label*="Mixed" i]',
        'button[title*="Número mixto" i]',
        '[class*="mixed_button"]',
    ],
    "not_equal": [
        'button[title*="Not equal" i]',
        'button:has-text("≠")',
        'button[title="≠"]',
    ],
    "less_equal": [
        'button[title*="Less than or equal" i]',
        'button:has-text("≤")',
        'button[title="≤"]',
    ],
    "greater_equal": [
        'button[title*="Greater than or equal" i]',
        'button:has-text("≥")',
        'button[title="≥"]',
    ],
}

# Keyboard shortcuts ALEKS accepts in its math editor
_KEYBOARD_SHORTCUTS = {
    "fraction": "/",
}

# JS text-hint fallback for each tool button
_BUTTON_TEXT_HINTS = {
    "pi":             ["π", "pi", "Pi", "PI"],
    "sqrt":           ["√", "square root", "Square Root", "raíz", "Raíz"],
    "fraction":       ["/", "fraction", "Fraction", "fracción", "Fracción"],
    "exponent":       ["^", "exponent", "Exponent", "exponente"],
    "absolute_value": ["|•|", "|", "absolute", "Absolute", "valor absoluto"],
    "mixed_number":   ["mixed", "Mixed", "mixto", "Mixto"],
    "not_equal":      ["≠"],
    "less_equal":     ["≤"],
    "greater_equal":  ["≥"],
}


class ALEKSInputLayer:
    """
    Automated math input layer for ALEKS.

    Usage:
        layer = ALEKSInputLayer(page)
        layer.input_answer(ai_answer_string_or_json)
        layer.submit_answer()
    """

    def __init__(self, page, solver=None):
        self.page   = page
        self.solver = solver   # optional ChatbotSolver for vision fallbacks

    # ═══════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ═══════════════════════════════════════════════════════════════════

    def input_answer(self, answer: str) -> bool:
        """
        Master entry point. Accepts:
          • Raw answer string: "3/4", "sqrt(16)", "x^2 + 3", "42"
          • JSON string: '{"type":"fraction","numerator":"3","denominator":"4"}'
          • Dict already parsed from JSON
        """
        if not answer:
            log.warning("input_answer: empty answer — skipping")
            return False

        if isinstance(answer, dict):
            data = answer
        else:
            answer = answer.strip()
            data = None
            if answer.startswith("{"):
                try:
                    data = json.loads(answer)
                except json.JSONDecodeError:
                    pass

        if data is not None:
            if data.get("type", "simple").lower() != "graph":
                self._focus_editor()
                self._clear_editor()
            return self._dispatch_json(data)

        self._focus_editor()
        self._clear_editor()
        return self._input_expression(answer)

    def submit_answer(self) -> bool:
        """Click Check / Verificar / Submit. Falls back to Enter."""
        submit_selectors = [
            'button:has-text("Check")',
            'button:has-text("Verificar")',
            'button:has-text("Submit")',
            'button:has-text("Entregar")',
            'button[class*="submit"]',
            'button[class*="check"]',
            'input[type="submit"]',
            '[class*="checkButton"]',
            '[class*="submitButton"]',
        ]
        for sel in submit_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=2_000):
                    btn.click(timeout=3_000)
                    log.info(f"  Submitted via {sel}")
                    time.sleep(1.5)
                    return True
            except Exception:
                continue

        submit_hints = ["Check", "Verificar", "Submit", "Entregar", "OK", "Aceptar"]
        coord = self.page.evaluate("""
            (hints) => {
                const els = Array.from(document.querySelectorAll(
                    'button, input[type="submit"], input[type="button"], [role="button"]'
                ));
                for (const el of els) {
                    if (!el.offsetParent) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 5 || r.height < 5) continue;
                    const t = (el.textContent || el.value || '').trim();
                    for (const h of hints) {
                        if (t.toLowerCase().includes(h.toLowerCase()))
                            return { x: r.left + r.width/2, y: r.top + r.height/2 };
                    }
                }
                return null;
            }
        """, submit_hints)

        if coord:
            self.page.mouse.click(coord["x"], coord["y"])
            log.info(f"  Submitted via JS coord")
            time.sleep(1.5)
            return True

        log.warning("  submit_answer: no button found — pressing Enter")
        self.page.keyboard.press("Enter")
        time.sleep(1.5)
        return False

    # ═══════════════════════════════════════════════════════════════════
    #  EDITOR FOCUS & CLEAR
    # ═══════════════════════════════════════════════════════════════════

    def _focus_editor(self) -> bool:
        """
        Click the ALEKS ansed math editor to give it keyboard focus.

        ALEKS renders its answer editor as a div with class 'ansed_root'.
        Clicking the CENTER of this div activates ALEKS's keyboard listeners.
        This is the ONLY reliable focus method — .focus() alone doesn't work
        on canvas/custom editors.
        """
        # ── 1. JS coord scan: find .ansed_root ───────────────────────────
        coord = self.page.evaluate(r"""
            () => {
                // ALEKS answer editor classes (confirmed from DOM inspection)
                const selectors = [
                    '.ansed_root',
                    '[class*="ansed_root"]',
                    '[id*="ansed_root"]',
                    '[class*="ansed-root"]',
                    // Canvas inside the editor (some ALEKS versions)
                    '[class*="ansed"] canvas',
                    '[id*="ansed"] canvas',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (!el || !el.offsetParent) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 10 || r.height < 10) continue;
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2, sel };
                }

                // ── Fallback: plain text inputs below y=100 ──────────────
                const inputs = Array.from(
                    document.querySelectorAll('input[type="text"], input:not([type])')
                ).filter(el => {
                    if (!el.offsetParent) return false;
                    const cls = (el.className || '').toLowerCase();
                    const id  = (el.id  || '').toLowerCase();
                    if (cls.includes('search') || cls.includes('filter') ||
                        id.includes('search')  || id.includes('login') ||
                        id.includes('nav'))     return false;
                    const r = el.getBoundingClientRect();
                    return r.top > 100 && r.width > 20;
                });
                if (inputs.length) {
                    const r = inputs[0].getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2, sel: 'input' };
                }
                return null;
            }
        """)

        if coord:
            self.page.mouse.click(coord["x"], coord["y"])
            log.info(f"  Focused editor ({coord['sel']})")
            time.sleep(0.4)
            return True

        # ── 2. Playwright locator fallback ────────────────────────────────
        for sel in ['.ansed_root', '[class*="ansed_root"]',
                    'input[class*="answer"]', '#answer_input']:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    log.info(f"  Focused via locator ({sel})")
                    time.sleep(0.3)
                    return True
            except Exception:
                continue

        log.warning("  _focus_editor: no editor found")
        return False

    def _refocus(self):
        """
        Re-click the math editor after a toolbar button click.

        Toolbar button clicks (fraction, sqrt, π, etc.) can steal keyboard
        focus away from the math editor. This call restores focus so that
        subsequent keyboard.type / keyboard.press go into the editor.

        Called after EVERY _click_tool_button() that returns True.
        """
        coord = self.page.evaluate(r"""
            () => {
                const el = document.querySelector(
                    '.ansed_root, [class*="ansed_root"], [id*="ansed_root"]'
                );
                if (!el || !el.offsetParent) return null;
                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 10) return null;
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
        """)
        if coord:
            self.page.mouse.click(coord["x"], coord["y"])
            time.sleep(0.2)

    def _clear_editor(self):
        """
        Clear the ALEKS math editor content.

        Does NOT use Control+A — that selects all page text when focus is on
        the page body instead of the editor, causing the blue text-selection
        effect seen in screenshots.

        Strategy:
          1. Try the ALEKS Clear (×) toolbar button first (most reliable)
          2. End → 30× Backspace to erase tokens one by one
        """
        # ── 1. ALEKS Clear button (fastest) ──────────────────────────────
        for sel in [
            'button[title*="Clear" i]',
            'button[aria-label*="Clear" i]',
            'button[title*="Limpiar" i]',
            '[class*="clear_button"]',
            '[class*="clearButton"]',
        ]:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    log.info(f"  Cleared via Clear button ({sel})")
                    time.sleep(0.3)
                    self._refocus()   # restore editor focus after button click
                    return
            except Exception:
                continue

        # ── 2. End + Backspace loop ───────────────────────────────────────
        self.page.keyboard.press("End")
        time.sleep(0.05)
        for _ in range(30):
            self.page.keyboard.press("Backspace")
            time.sleep(0.03)

    # ═══════════════════════════════════════════════════════════════════
    #  JSON DISPATCHER
    # ═══════════════════════════════════════════════════════════════════

    def _dispatch_json(self, data: dict) -> bool:
        atype = data.get("type", "simple").lower()

        if atype == "simple":
            return self._input_expression(str(data.get("value", "")))
        elif atype == "fraction":
            self._input_fraction(
                str(data.get("numerator", "")),
                str(data.get("denominator", ""))
            )
            return True
        elif atype == "sqrt":
            self._input_sqrt(str(data.get("radicand", "")))
            return True
        elif atype == "exponent":
            self._input_exponent(
                str(data.get("base", "")),
                str(data.get("exponent", data.get("exp", "")))
            )
            return True
        elif atype == "mixed":
            self._input_mixed(
                str(data.get("whole", "")),
                str(data.get("numerator", "")),
                str(data.get("denominator", ""))
            )
            return True
        elif atype == "graph":
            return self._input_graph(data)
        elif atype in ("expression", "equation", "inequality"):
            val = data.get("value", data.get("raw", data.get("answer", "")))
            return self._input_expression(str(val))
        else:
            val = data.get("value", data.get("answer", data.get("raw", "")))
            return self._input_expression(str(val))

    # ═══════════════════════════════════════════════════════════════════
    #  BUTTON CLICK  (with mandatory refocus after every click)
    # ═══════════════════════════════════════════════════════════════════

    def _click_tool_button(self, tool: str) -> bool:
        """
        Click an ALEKS math palette tool button.

        After a successful button click, always call _refocus() so the math
        editor regains keyboard focus before the next keyboard.type/press.

        Strategy chain:
          1. Playwright selectors (aria/title/class/text)
          2. JS coordinate scan — text-content matching
          3. Keyboard shortcut (if defined)

        Returns True if the tool was activated.
        """
        # ── Strategy 1: Playwright selectors ─────────────────────────────
        for sel in _BUTTON_SELECTORS.get(tool, []):
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    log.info(f"  Clicked '{tool}' button ({sel})")
                    time.sleep(0.3)
                    self._refocus()   # ← restore editor focus
                    return True
            except Exception:
                continue

        # ── Strategy 2: JS coordinate scan ───────────────────────────────
        hints = _BUTTON_TEXT_HINTS.get(tool, [])
        if hints:
            hints_js = json.dumps(hints)
            coord = self.page.evaluate(f"""
                (hints) => {{
                    const candidates = Array.from(document.querySelectorAll(
                        'button, input[type="button"], [role="button"], ' +
                        '[class*="tool"], [class*="btn"], [class*="button"]'
                    ));
                    for (const el of candidates) {{
                        if (!el.offsetParent) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width < 5 || r.height < 5) continue;
                        const text  = (el.textContent  || '').trim();
                        const title = (el.title        || '').trim();
                        const label = (el.getAttribute('aria-label') || '').trim();
                        for (const hint of hints) {{
                            if (text  === hint || text.toLowerCase()  === hint.toLowerCase() ||
                                title === hint || title.toLowerCase() === hint.toLowerCase() ||
                                label === hint || label.toLowerCase() === hint.toLowerCase()) {{
                                return {{ x: r.left + r.width  / 2,
                                          y: r.top  + r.height / 2 }};
                            }}
                        }}
                    }}
                    return null;
                }}
            """, hints_js)

            if coord:
                self.page.mouse.click(coord["x"], coord["y"])
                log.info(f"  Clicked '{tool}' button via JS coords")
                time.sleep(0.3)
                self._refocus()   # ← restore editor focus
                return True

        # ── Strategy 3: keyboard shortcut (no refocus needed — key event) ─
        shortcut = _KEYBOARD_SHORTCUTS.get(tool)
        if shortcut:
            self.page.keyboard.press(shortcut)
            log.info(f"  Activated '{tool}' via shortcut '{shortcut}'")
            time.sleep(0.2)
            return True

        log.warning(f"  Could not activate '{tool}' tool — all strategies failed")
        return False

    # ═══════════════════════════════════════════════════════════════════
    #  EXPRESSION PARSER & TOKENIZER
    # ═══════════════════════════════════════════════════════════════════

    def _input_expression(self, expr: str) -> bool:
        tokens = self._tokenize(expr.strip())
        log.info(f"  Tokens: {tokens}")
        for tok in tokens:
            self._process_token(tok)
            time.sleep(0.1)
        return True

    _TRIG_FNS = [
        "arcsin", "arccos", "arctan",
        "sinh", "cosh", "tanh",
        "sin", "cos", "tan", "sec", "csc", "cot",
        "log", "ln", "exp",
    ]

    def _tokenize(self, s: str) -> list:
        """
        Break expression into typed token dicts.

        Token types: "text", "fraction", "sqrt", "exponent",
                     "mixed", "pi", "abs", "trig"
        """
        s = s.strip()

        # ── Whole-expression shortcuts ────────────────────────────────────

        m = re.fullmatch(r"(-?\d+)\s*/\s*(-?\d+)", s)
        if m:
            return [{"type": "fraction", "num": m.group(1), "denom": m.group(2)}]

        m = re.fullmatch(r"(-?\d+)\s+(\d+)\s*/\s*(\d+)", s)
        if m:
            return [{"type": "mixed",
                     "whole": m.group(1), "num": m.group(2), "denom": m.group(3)}]

        m = re.fullmatch(r"sqrt\((.+)\)", s, re.IGNORECASE)
        if m:
            return [{"type": "sqrt", "radicand": m.group(1)}]

        m = re.fullmatch(r"√(.+)", s)
        if m:
            return [{"type": "sqrt", "radicand": m.group(1)}]

        if s.lower() in ("pi", "π"):
            return [{"type": "pi"}]

        # ── Character-by-character scan ───────────────────────────────────
        tokens: list = []
        buf = ""
        i = 0

        def flush():
            nonlocal buf
            if buf:
                tokens.append({"type": "text", "value": buf})
                buf = ""

        def _find_matching_paren(src: str, start: int) -> int:
            depth = 0
            j = start
            while j < len(src):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                    if depth == 0:
                        return j
                j += 1
            return j - 1

        while i < len(s):
            c = s[i]

            # ── sqrt(...) ─────────────────────────────────────────────────
            if s[i:i+4].lower() == "sqrt" and i + 4 < len(s) and s[i + 4] == "(":
                flush()
                close = _find_matching_paren(s, i + 4)
                tokens.append({"type": "sqrt", "radicand": s[i + 5:close]})
                i = close + 1
                continue

            # ── Unicode √ ─────────────────────────────────────────────────
            if c == "√":
                flush()
                j = i + 1
                while j < len(s) and s[j] not in " +\n":
                    j += 1
                tokens.append({"type": "sqrt", "radicand": s[i + 1:j]})
                i = j
                continue

            # ── Trig / math functions: sin(...) cos(...) etc. ─────────────
            matched_fn = None
            for fn in self._TRIG_FNS:
                fl = len(fn)
                if (s[i:i+fl].lower() == fn
                        and i + fl < len(s)
                        and s[i + fl] == "("):
                    matched_fn = fn
                    break
            if matched_fn:
                flush()
                fl = len(matched_fn)
                close = _find_matching_paren(s, i + fl)
                inner = s[i + fl + 1:close]
                tokens.append({"type": "trig", "fn": matched_fn.lower(), "arg": inner})
                i = close + 1
                continue

            # ── Absolute value |...| ──────────────────────────────────────
            if c == "|":
                flush()
                j = s.find("|", i + 1)
                if j != -1:
                    tokens.append({"type": "abs", "content": s[i + 1:j]})
                    i = j + 1
                else:
                    buf += c
                    i += 1
                continue

            # ── π symbol ──────────────────────────────────────────────────
            if c == "π":
                flush()
                tokens.append({"type": "pi"})
                i += 1
                continue

            # ── "pi" word ─────────────────────────────────────────────────
            if s[i:i+2].lower() == "pi":
                after = s[i + 2] if i + 2 < len(s) else ""
                after2 = s[i + 3] if i + 3 < len(s) else ""
                is_standalone = not after.isalpha()
                is_pi_var = after.isalpha() and not after2.isalpha()
                if is_standalone or is_pi_var:
                    flush()
                    tokens.append({"type": "pi"})
                    i += 2
                    continue

            # ── Fraction via / ────────────────────────────────────────────
            # Catches: 3/4, t/4, πt/4, 2t/3, etc.
            # Absorbs a preceding pi token into the numerator so that
            # "πt/4" → fraction(πt, 4) not [pi] + fraction(t, 4).
            # This keeps π inside the fraction box rather than as a separate
            # element that would require an extra button/keyboard click.
            if c == "/" and buf and buf.strip():
                num = buf.strip()
                buf = ""
                if tokens and tokens[-1].get("type") == "pi":
                    tokens.pop()
                    num = "π" + num
                i += 1
                denom_buf = ""
                while i < len(s) and (s[i].isdigit() or (not denom_buf and s[i] == "-")):
                    denom_buf += s[i]
                    i += 1
                if denom_buf:
                    tokens.append({"type": "fraction", "num": num, "denom": denom_buf})
                else:
                    tokens.append({"type": "text", "value": num + "/"})
                continue

            # ── Exponent via ^ ────────────────────────────────────────────
            if c == "^":
                base = buf.strip()
                buf = ""
                i += 1
                if i < len(s) and s[i] == "(":
                    close = _find_matching_paren(s, i)
                    exp_buf = s[i + 1:close]
                    i = close + 1
                else:
                    exp_buf = ""
                    while i < len(s) and (s[i].isalnum() or s[i] in ".-_"):
                        exp_buf += s[i]
                        i += 1
                if base:
                    tokens.append({"type": "exponent", "base": base, "exp": exp_buf})
                else:
                    tokens.append({"type": "text", "value": "^" + exp_buf})
                continue

            buf += c
            i += 1

        flush()
        return tokens or [{"type": "text", "value": s}]

    def _process_token(self, tok: dict):
        """Dispatch a single token to the correct input method."""
        t = tok["type"]
        if t == "text":
            self._type_raw(tok["value"])
        elif t == "fraction":
            self._input_fraction(tok["num"], tok["denom"])
        elif t == "sqrt":
            self._input_sqrt(tok["radicand"])
        elif t == "exponent":
            self._input_exponent(tok["base"], tok["exp"])
        elif t == "mixed":
            self._input_mixed(tok["whole"], tok["num"], tok["denom"])
        elif t == "pi":
            self._input_pi()
        elif t == "abs":
            self._input_absolute(tok.get("content", ""))
        elif t == "trig":
            self._input_trig(tok["fn"], tok["arg"])

    # ═══════════════════════════════════════════════════════════════════
    #  PRIMITIVE INPUT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════

    def _type_raw(self, text: str):
        """
        Type plain text via keyboard.type() which fires real key events.
        Must NOT use insert_text — ALEKS's math editor intercepts key events
        to build its internal token tree; insert_text bypasses those handlers.
        """
        if not text:
            return
        self.page.keyboard.type(text, delay=40)
        time.sleep(0.05)

    def _input_fraction(self, num: str, denom: str):
        """
        Press / keyboard shortcut → type numerator → Tab → type denominator → Tab.

        Uses the keyboard shortcut ONLY (never button click) so that focus
        stays inside any enclosing template box (e.g. the cos argument box).
        Clicking the fraction toolbar button + _refocus() would exit a nested
        template box and leave it empty.
        """
        log.info(f"  fraction({num}/{denom})")
        self.page.keyboard.press("/")
        time.sleep(0.25)
        for tok in self._tokenize(num):
            self._process_token(tok)
        self.page.keyboard.press("Tab")
        time.sleep(0.2)
        for tok in self._tokenize(denom):
            self._process_token(tok)
        self.page.keyboard.press("Tab")
        time.sleep(0.2)

    def _input_sqrt(self, radicand: str):
        """Click sqrt button → type radicand → Tab."""
        log.info(f"  sqrt({radicand})")
        activated = self._click_tool_button("sqrt")   # refocus happens inside
        time.sleep(0.3)
        if not activated:
            self._type_raw(f"sqrt({radicand})")
            return
        for tok in self._tokenize(radicand):
            self._process_token(tok)
        self.page.keyboard.press("Tab")
        time.sleep(0.2)

    def _input_exponent(self, base: str, exp: str):
        """Type base → ^ → type exponent → Tab."""
        log.info(f"  exponent({base}^{exp})")
        for tok in self._tokenize(base):
            self._process_token(tok)
        self.page.keyboard.type("^", delay=20)
        time.sleep(0.3)
        for tok in self._tokenize(exp):
            self._process_token(tok)
        self.page.keyboard.press("Tab")
        time.sleep(0.2)

    def _input_mixed(self, whole: str, num: str, denom: str):
        """Click mixed-number button → whole → Tab → num → Tab → denom → Tab."""
        log.info(f"  mixed({whole} {num}/{denom})")
        activated = self._click_tool_button("mixed_number")   # refocus inside
        time.sleep(0.25)
        if activated:
            self._type_raw(whole)
            self.page.keyboard.press("Tab")
            time.sleep(0.2)
            self._type_raw(num)
            self.page.keyboard.press("Tab")
            time.sleep(0.2)
            self._type_raw(denom)
            self.page.keyboard.press("Tab")
            time.sleep(0.2)
        else:
            self._type_raw(whole)
            time.sleep(0.1)
            self._input_fraction(num, denom)

    def _input_pi(self):
        """
        Click the π toolbar button, then refocus.
        Falls back to typing π directly if button not found.

        The button click is preferred (produces the proper ALEKS π token),
        and _click_tool_button always calls _refocus() after clicking so
        keyboard focus returns to the math editor immediately.
        """
        log.info("  pi()")
        activated = self._click_tool_button("pi")   # refocus happens inside
        if not activated:
            self.page.keyboard.type("π", delay=40)

    def _input_absolute(self, content: str):
        """Click absolute-value button → type content → Tab."""
        log.info(f"  abs({content})")
        self._click_tool_button("absolute_value")   # refocus inside
        time.sleep(0.2)
        for tok in self._tokenize(content):
            self._process_token(tok)
        self.page.keyboard.press("Tab")
        time.sleep(0.2)

    def _input_trig(self, fn: str, arg: str):
        """
        Input a trig/math function call: fn(arg).

        ALEKS intercepts typing "sin"/"cos"/etc. and auto-creates a template
        with an argument box [□].  Do NOT type "(" — that places text outside
        the box.  Type the function name, wait for ALEKS to render the template,
        then type the argument directly inside the box, then Tab to exit.
        """
        log.info(f"  trig({fn}({arg}))")
        self.page.keyboard.type(fn, delay=40)
        time.sleep(0.3)   # wait for ALEKS to render template
        for tok in self._tokenize(arg):
            self._process_token(tok)
            time.sleep(0.08)
        self.page.keyboard.press("Tab")
        time.sleep(0.2)

    # ═══════════════════════════════════════════════════════════════════
    #  GRAPH INPUT
    # ═══════════════════════════════════════════════════════════════════

    def _input_graph(self, data: dict) -> bool:
        """
        Plot points on the ALEKS interactive graph.

        data = {"type": "graph", "points": [[x1,y1], [x2,y2], ...]}
        """
        points = data.get("points", [])
        if not points:
            log.warning("  _input_graph: no points in data")
            return False

        log.info(f"  Plotting {len(points)} graph point(s): {points}")

        canvas = self.page.evaluate(r"""
            () => {
                const canvas = document.querySelector(
                    'canvas[id*="graph"], canvas[class*="graph"], ' +
                    '[class*="graphCanvas"], [id*="graphCanvas"], ' +
                    'canvas[id*="aleks"], canvas'
                );
                if (!canvas) return null;
                const r = canvas.getBoundingClientRect();

                // Read axis ranges from DOM data attributes — return null if absent
                // so the Python side can ask the chatbot instead of guessing.
                function readAttr(el, ...keys) {
                    for (const k of keys) {
                        const v = el.dataset[k] ?? el.getAttribute('data-' + k.replace(/([A-Z])/g, '-$1').toLowerCase());
                        if (v !== null && v !== undefined && v !== '') {
                            const n = parseFloat(v);
                            if (!isNaN(n)) return n;
                        }
                    }
                    return null;
                }

                return {
                    left:  r.left,  top:    r.top,
                    width: r.width, height: r.height,
                    xMin:  readAttr(canvas, 'xMin', 'minx', 'x-min'),
                    xMax:  readAttr(canvas, 'xMax', 'maxx', 'x-max'),
                    yMin:  readAttr(canvas, 'yMin', 'miny', 'y-min'),
                    yMax:  readAttr(canvas, 'yMax', 'maxy', 'y-max'),
                };
            }
        """)

        if not canvas:
            log.warning("  _input_graph: graph canvas not found")
            return False

        # ── Ask chatbot for axis ranges if DOM data attributes are missing ─
        missing = any(canvas.get(k) is None for k in ('xMin', 'xMax', 'yMin', 'yMax'))
        if missing:
            axes = None
            if self.solver is not None:
                try:
                    from pathlib import Path as _Path
                    tmp = _Path(__file__).parent / "screenshots" / "_graph_axes.png"
                    self.page.screenshot(path=str(tmp))
                    axes = self.solver.classify_graph_axes(tmp)
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
                except Exception as e:
                    log.warning(f"  _input_graph: axis chatbot call failed: {e}")
            if axes:
                canvas.update(axes)
                log.info(f"  _input_graph: axes from chatbot → {axes}")
            else:
                log.warning("  _input_graph: axis ranges unknown — defaulting to [-10, 10]")
                canvas.setdefault('xMin', -10); canvas.setdefault('xMax', 10)
                canvas.setdefault('yMin', -10); canvas.setdefault('yMax', 10)

        def _to_pixel(mx, my):
            xr = canvas["xMax"] - canvas["xMin"]
            yr = canvas["yMax"] - canvas["yMin"]
            px = canvas["left"] + (mx - canvas["xMin"]) / xr * canvas["width"]
            py = canvas["top"]  + (canvas["yMax"] - my)  / yr * canvas["height"]
            return px, py

        for pt in points:
            if len(pt) < 2:
                continue
            mx, my = float(pt[0]), float(pt[1])
            px, py = _to_pixel(mx, my)
            log.info(f"    ({mx}, {my}) → pixel ({px:.0f}, {py:.0f})")
            self.page.mouse.click(px, py)
            time.sleep(0.6)

        return True
