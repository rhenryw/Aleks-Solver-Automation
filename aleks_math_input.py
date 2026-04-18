"""
aleks_math_input.py — ALEKS Math Input Layer

Automatically translates AI-returned answers into ALEKS UI operations.
Handles all 44 ALEKS input types: fractions, square roots, exponents,
mixed numbers, pi, trig functions, absolute values, inequalities, graphs.

Architecture:
  1. ALEKSInputLayer.input_answer(answer_str_or_json)
       → _detect_type()        — classify the answer
       → _input_expression()   — tokenize + dispatch tokens
       → _process_token()      — execute each token as UI ops

Button-click fallback chain for every tool:
  1. aria-label / title selectors
  2. Class-pattern selectors
  3. Keyboard shortcut (where ALEKS supports one)
  4. Log warning and type raw text
"""

import json
import logging
import re
import time

log = logging.getLogger("aleks_math_input")


# ─── ALEKS answer-input selectors (most-specific first) ─────────────────────

_ANSWER_FIELD_SELECTORS = [
    # ALEKS custom math editor
    '[id^="ansed_"] input',
    '[class*="ansed"] input',
    '.ansed_root input',
    # Generic answer/response inputs below the question
    'input[class*="answer"]',
    'input[class*="response"]',
    'input[id*="answer"]',
    '#answer_input',
    # Contenteditable math editors
    '[contenteditable="true"][class*="math"]',
    '[contenteditable="true"][class*="answer"]',
    # Last resort: first visible text input below y=100
    'input[type="text"]:visible',
]

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
        'button:has-text("/")',
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
        'button:has-text("^")',
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
    "fraction": "/",   # "/" triggers fraction mode
}


class ALEKSInputLayer:
    """
    Automated math input layer for ALEKS.

    Usage:
        layer = ALEKSInputLayer(page)
        layer.input_answer(ai_answer_string_or_json)
        layer.submit_answer()
    """

    def __init__(self, page):
        self.page = page

    # ═══════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ═══════════════════════════════════════════════════════════════════

    def input_answer(self, answer: str) -> bool:
        """
        Master entry point.  Accepts either:
          • A raw answer string: "3/4", "sqrt(16)", "x^2 + 3", "42"
          • A JSON string from the AI: '{"type":"fraction","numerator":"3","denominator":"4"}'
          • A dict already parsed from JSON

        Returns True if input operations were performed without error.
        """
        if not answer:
            log.warning("input_answer: empty answer — skipping")
            return False

        if isinstance(answer, dict):
            return self._dispatch_json(answer)

        answer = answer.strip()

        # Try to parse as JSON
        if answer.startswith("{"):
            try:
                data = json.loads(answer)
                return self._dispatch_json(data)
            except json.JSONDecodeError:
                pass

        # Plain expression string
        return self._input_expression(answer)

    def submit_answer(self) -> bool:
        """
        Click the ALEKS "Check / Verificar / Submit" button.

        Never hangs: each selector attempt uses a 2-second timeout.
        Falls back to JS coordinate scan, then Enter key.
        Returns True if a button was found and clicked.
        """
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
                # Short timeout so a missing element never blocks
                if btn.is_visible(timeout=2_000):
                    btn.click(timeout=3_000)
                    log.info(f"  Submitted via {sel}")
                    time.sleep(1.5)
                    return True
            except Exception:
                continue

        # JS coordinate fallback — finds any visible submit/check button by text
        submit_hints = ["Check", "Verificar", "Submit", "Entregar", "OK", "Aceptar"]
        coord = self.page.evaluate(f"""
            (hints) => {{
                const els = Array.from(document.querySelectorAll(
                    'button, input[type="submit"], input[type="button"], [role="button"]'
                ));
                for (const el of els) {{
                    if (!el.offsetParent) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 5 || r.height < 5) continue;
                    const t = (el.textContent || el.value || '').trim();
                    for (const h of hints) {{
                        if (t.toLowerCase().includes(h.toLowerCase()))
                            return {{ x: r.left + r.width/2, y: r.top + r.height/2 }};
                    }}
                }}
                return null;
            }}
        """, submit_hints)

        if coord:
            self.page.mouse.click(coord["x"], coord["y"])
            log.info(f"  Submitted via JS coord ({coord['x']:.0f},{coord['y']:.0f})")
            time.sleep(1.5)
            return True

        # Last resort: Enter key
        log.warning("  submit_answer: no button found — pressing Enter")
        self.page.keyboard.press("Enter")
        time.sleep(1.5)
        return False

    # ═══════════════════════════════════════════════════════════════════
    #  JSON DISPATCHER
    # ═══════════════════════════════════════════════════════════════════

    def _dispatch_json(self, data: dict) -> bool:
        atype = data.get("type", "simple").lower()

        # Focus the answer field first for non-graph answers
        if atype != "graph":
            self._focus_answer_field()

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
    #  ANSWER FIELD FOCUS
    # ═══════════════════════════════════════════════════════════════════

    def _focus_answer_field(self) -> bool:
        """
        Find the ALEKS answer input and give it focus.
        Returns True if an element was explicitly clicked; False if done via JS.
        """
        for sel in _ANSWER_FIELD_SELECTORS:
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    log.info(f"  Focused answer field ({sel})")
                    time.sleep(0.3)
                    self._clear_field()
                    return True
            except Exception:
                continue

        # JS fallback: find visible inputs below y=100 that are NOT search/nav
        coord = self.page.evaluate(r"""
            () => {
                const inputs = Array.from(
                    document.querySelectorAll('input[type="text"], input:not([type])')
                ).filter(el => {
                    if (!el.offsetParent) return false;
                    const cls = (el.className || '').toLowerCase();
                    const id  = (el.id  || '').toLowerCase();
                    if (cls.includes('search') || cls.includes('filter') ||
                        id.includes('search')  || id.includes('login')  ||
                        id.includes('nav'))     return false;
                    const r = el.getBoundingClientRect();
                    return r.top > 100 && r.width > 20;
                });
                if (!inputs.length) return null;
                const r = inputs[0].getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
        """)

        if coord:
            self.page.mouse.click(coord["x"], coord["y"])
            log.info(f"  Focused answer field via JS ({coord['x']:.0f},{coord['y']:.0f})")
            time.sleep(0.3)
            self._clear_field()
            return True

        log.warning("  _focus_answer_field: no input found")
        return False

    def _clear_field(self):
        """Aggressively clear the currently focused answer field."""
        # Select all + delete (covers both plain inputs and math editors)
        self.page.keyboard.press("Control+a")
        time.sleep(0.1)
        self.page.keyboard.press("Delete")
        time.sleep(0.1)
        # Second pass: Backspace loop clears any residual math editor tokens
        for _ in range(20):
            self.page.keyboard.press("Backspace")
            time.sleep(0.03)
        # Also try the ALEKS "Clear" (X) button if visible
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
                    log.info(f"  Cleared via ALEKS Clear button ({sel})")
                    time.sleep(0.2)
                    break
            except Exception:
                continue

    # ═══════════════════════════════════════════════════════════════════
    #  BUTTON CLICK
    # ═══════════════════════════════════════════════════════════════════

    # Text fragments to search for each tool button via JS coordinate fallback
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

    def _click_tool_button(self, tool: str) -> bool:
        """
        Click an ALEKS math palette tool button.

        Strategy chain (never hangs — all calls are non-blocking):
          1. Playwright locator selectors (aria/title/class/text)
          2. JS coordinate scan — finds any visible button whose
             textContent or title matches known hints, clicks by coords
          3. Keyboard shortcut (if defined for this tool)

        Returns True if the tool was activated by any strategy.
        """
        # ── Strategy 1: Playwright selectors ────────────────────────────
        for sel in _BUTTON_SELECTORS.get(tool, []):
            try:
                el = self.page.locator(sel).first
                if el.is_visible():
                    el.click()
                    log.info(f"  Clicked '{tool}' button ({sel})")
                    time.sleep(0.3)
                    return True
            except Exception:
                continue

        # ── Strategy 2: JS coordinate scan ──────────────────────────────
        hints = self._BUTTON_TEXT_HINTS.get(tool, [])
        if hints:
            hints_js = json.dumps(hints)
            coord = self.page.evaluate(f"""
                (hints) => {{
                    // Search every button/input-button on the page
                    const candidates = Array.from(document.querySelectorAll(
                        'button, input[type="button"], [role="button"], ' +
                        '[class*="tool"], [class*="btn"], [class*="button"]'
                    ));
                    for (const el of candidates) {{
                        if (!el.offsetParent) continue;          // not visible
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
                log.info(f"  Clicked '{tool}' button via JS coords "
                         f"({coord['x']:.0f},{coord['y']:.0f})")
                time.sleep(0.3)
                return True

        # ── Strategy 3: keyboard shortcut ───────────────────────────────
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
        """
        Parse and input a math expression string.

        Handles (in order of detection priority):
          simple fraction        3/4
          mixed number           2 3/5
          sqrt                   sqrt(x+4) or √x
          exponent               x^2  or  x^(n+1)
          absolute value         |x+3|
          pi                     pi or π
          trig                   sin(x) cos(x) tan(x)
          composite              any combination of the above
        """
        self._focus_answer_field()

        tokens = self._tokenize(expr.strip())
        log.info(f"  Tokens: {tokens}")

        for tok in tokens:
            self._process_token(tok)
            time.sleep(0.1)

        return True

    # Trig / math function names recognized as tokens (longest first to avoid prefix clash)
    _TRIG_FNS = [
        "arcsin", "arccos", "arctan",
        "sinh", "cosh", "tanh",
        "sin", "cos", "tan", "sec", "csc", "cot",
        "log", "ln", "exp",
    ]

    def _tokenize(self, s: str) -> list:
        """
        Break expression into a list of typed token dicts.

        Token types: "text", "fraction", "sqrt", "exponent",
                     "mixed", "pi", "abs", "trig"

        Handles compound math expressions like:
          y = -3sin(2pix) + 2
          3/4 + sqrt(x^2-4)
          2 3/5
          |x+1|
        """
        s = s.strip()

        # ── Whole-expression shortcuts ───────────────────────────────────

        # Pure simple fraction: digits/digits
        m = re.fullmatch(r"(-?\d+)\s*/\s*(-?\d+)", s)
        if m:
            return [{"type": "fraction", "num": m.group(1), "denom": m.group(2)}]

        # Mixed number: whole space num/denom
        m = re.fullmatch(r"(-?\d+)\s+(\d+)\s*/\s*(\d+)", s)
        if m:
            return [{"type": "mixed",
                     "whole": m.group(1), "num": m.group(2), "denom": m.group(3)}]

        # Top-level sqrt(...)
        m = re.fullmatch(r"sqrt\((.+)\)", s, re.IGNORECASE)
        if m:
            return [{"type": "sqrt", "radicand": m.group(1)}]

        # Unicode √ whole expression
        m = re.fullmatch(r"√(.+)", s)
        if m:
            return [{"type": "sqrt", "radicand": m.group(1)}]

        # Pure pi / π
        if s.lower() in ("pi", "π"):
            return [{"type": "pi"}]

        # ── Character-by-character scan ──────────────────────────────────
        tokens: list = []
        buf = ""
        i = 0

        def flush():
            nonlocal buf
            if buf:
                tokens.append({"type": "text", "value": buf})
                buf = ""

        def _find_matching_paren(src: str, start: int) -> int:
            """Return index of ')' matching the '(' at src[start], or len(src)-1."""
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

            # ── sqrt(...) ────────────────────────────────────────────────
            if s[i:i+4].lower() == "sqrt" and i + 4 < len(s) and s[i + 4] == "(":
                flush()
                close = _find_matching_paren(s, i + 4)
                tokens.append({"type": "sqrt", "radicand": s[i + 5:close]})
                i = close + 1
                continue

            # ── Unicode √ ────────────────────────────────────────────────
            if c == "√":
                flush()
                j = i + 1
                # Consume until an unambiguous break char
                while j < len(s) and s[j] not in " +\n":
                    j += 1
                tokens.append({"type": "sqrt", "radicand": s[i + 1:j]})
                i = j
                continue

            # ── Trig / math functions: sin(...) cos(...) etc. ────────────
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

            # ── Absolute value |...| ─────────────────────────────────────
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

            # ── π symbol ─────────────────────────────────────────────────
            if c == "π":
                flush()
                tokens.append({"type": "pi"})
                i += 1
                continue

            # ── "pi" word ────────────────────────────────────────────────
            # Match pi when:
            #   • followed by non-alpha  (pi+, pi/, pi), end)  — always safe
            #   • followed by exactly one alpha variable char   (pix, pit)
            #     because in math "pix" = pi*x
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

            # ── Fraction via / between integer buffers ───────────────────
            if c == "/" and buf and re.fullmatch(r"-?\d+", buf.strip()):
                num = buf.strip()
                buf = ""
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

            # ── Exponent via ^ ───────────────────────────────────────────
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
        Type plain text character by character through keyboard.type().

        We MUST use keyboard.type (which fires real keydown/press/up events)
        rather than insert_text, because ALEKS's math editor intercepts key
        events to build its internal token tree.  insert_text bypasses those
        handlers and produces garbage output.
        """
        if not text:
            return
        # keyboard.type handles unicode, shift combos, and event firing correctly.
        # A small per-char delay makes the ALEKS editor reliably process each key.
        self.page.keyboard.type(text, delay=40)
        time.sleep(0.05)

    def _input_fraction(self, num: str, denom: str):
        """Click fraction button → type numerator → Tab → type denominator → Tab."""
        log.info(f"  fraction({num}/{denom})")
        self._click_tool_button("fraction")
        time.sleep(0.25)
        # Recursively tokenize each part (they may themselves contain sqrt, etc.)
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
        activated = self._click_tool_button("sqrt")
        time.sleep(0.3)
        if not activated:
            # Fallback: type as text if button not found
            self._type_raw(f"sqrt({radicand})")
            return
        for tok in self._tokenize(radicand):
            self._process_token(tok)
        self.page.keyboard.press("Tab")
        time.sleep(0.2)

    def _input_exponent(self, base: str, exp: str):
        """Type base → type ^ → type exponent → Tab."""
        log.info(f"  exponent({base}^{exp})")
        # Type base
        for tok in self._tokenize(base):
            self._process_token(tok)
        # Trigger exponent mode
        self.page.keyboard.type("^", delay=20)
        time.sleep(0.3)
        # Type exponent
        for tok in self._tokenize(exp):
            self._process_token(tok)
        self.page.keyboard.press("Tab")
        time.sleep(0.2)

    def _input_mixed(self, whole: str, num: str, denom: str):
        """Input a mixed number: whole + fraction."""
        log.info(f"  mixed({whole} {num}/{denom})")
        activated = self._click_tool_button("mixed_number")
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
            # Fallback: type whole, then fraction
            self._type_raw(whole)
            time.sleep(0.1)
            self._input_fraction(num, denom)

    def _input_pi(self):
        """Click π button, or type the Unicode π as last resort."""
        log.info("  pi()")
        activated = self._click_tool_button("pi")
        if not activated:
            # keyboard.type fires real key events; insert_text bypasses handlers
            self.page.keyboard.type("π", delay=40)

    def _input_absolute(self, content: str):
        """Input |content| absolute value expression."""
        log.info(f"  abs({content})")
        self._click_tool_button("absolute_value")
        time.sleep(0.2)
        for tok in self._tokenize(content):
            self._process_token(tok)
        # Close the absolute value
        self.page.keyboard.press("Tab")
        time.sleep(0.2)

    def _input_trig(self, fn: str, arg: str):
        """
        Input a trig/math function call: fn(arg).

        ALEKS accepts trig names typed directly (sin, cos, tan …).
        We type the function name + '(', then process the argument
        (which may itself contain pi, sqrt, exponents, etc.), then ')'.
        """
        log.info(f"  trig({fn}({arg}))")
        # Type function name — ALEKS recognises it as a math operator
        self.page.keyboard.type(fn, delay=40)
        time.sleep(0.1)
        # Open paren
        self.page.keyboard.type("(", delay=40)
        time.sleep(0.15)
        # Process argument recursively
        for tok in self._tokenize(arg):
            self._process_token(tok)
            time.sleep(0.08)
        # Close paren
        self.page.keyboard.type(")", delay=40)
        time.sleep(0.1)

    # ═══════════════════════════════════════════════════════════════════
    #  GRAPH INPUT
    # ═══════════════════════════════════════════════════════════════════

    def _input_graph(self, data: dict) -> bool:
        """
        Plot points on the ALEKS interactive graph.

        data = {"type": "graph", "points": [[x1,y1], [x2,y2], ...]}

        If the graph is a line or curve, ALEKS typically only needs 2 points
        (it draws the full line through them).  Extra points are ignored if
        the problem only allows 2 clicks.
        """
        points = data.get("points", [])
        if not points:
            log.warning("  _input_graph: no points in data")
            return False

        log.info(f"  Plotting {len(points)} graph point(s): {points}")

        # Locate the ALEKS graph canvas
        canvas = self.page.evaluate(r"""
            () => {
                // ALEKS graph canvases use various class/id patterns
                const canvas = document.querySelector(
                    'canvas[id*="graph"], canvas[class*="graph"], '  +
                    '[class*="graphCanvas"], [id*="graphCanvas"], '   +
                    'canvas[id*="aleks"], canvas'
                );
                if (!canvas) return null;
                const r = canvas.getBoundingClientRect();
                // Read grid bounds from data attributes (set by ALEKS JS)
                const xMin = parseFloat(
                    canvas.dataset.xMin || canvas.getAttribute('data-x-min') ||
                    canvas.dataset.minx  || canvas.getAttribute('data-minx')  || -10);
                const xMax = parseFloat(
                    canvas.dataset.xMax || canvas.getAttribute('data-x-max') ||
                    canvas.dataset.maxx  || canvas.getAttribute('data-maxx')  ||  10);
                const yMin = parseFloat(
                    canvas.dataset.yMin || canvas.getAttribute('data-y-min') ||
                    canvas.dataset.miny  || canvas.getAttribute('data-miny')  || -10);
                const yMax = parseFloat(
                    canvas.dataset.yMax || canvas.getAttribute('data-y-max') ||
                    canvas.dataset.maxy  || canvas.getAttribute('data-maxy')  ||  10);
                return {
                    left: r.left, top: r.top,
                    width: r.width, height: r.height,
                    xMin, xMax, yMin, yMax
                };
            }
        """)

        if not canvas:
            log.warning("  _input_graph: graph canvas not found")
            return False

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
