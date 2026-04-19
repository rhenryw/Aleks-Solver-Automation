"""
simulate_input.py — Dry-run simulation of ALEKSInputLayer

Mocks the Playwright page object so we can trace every action
without a live browser. Prints a numbered action log.

Run:
    python simulate_input.py
"""

import time as _time_module
import logging

# ── Silence the real time.sleep so the sim is instant ────────────────────────
import unittest.mock as mock

# Patch time.sleep globally before importing the module under test
_time_patcher = mock.patch("time.sleep", return_value=None)
_time_patcher.start()

# ── Minimal Playwright mock ───────────────────────────────────────────────────

class MockKeyboard:
    def __init__(self, log):
        self._log = log

    def type(self, text, delay=0):
        self._log(f"keyboard.type({text!r})")

    def press(self, key):
        self._log(f"keyboard.press({key!r})")

    def insert_text(self, text):
        self._log(f"keyboard.insert_text({text!r})")


class MockLocator:
    """Always pretends to be invisible so all locator selectors fail gracefully."""
    def first(self):
        return self
    def is_visible(self, timeout=None):
        return False
    def click(self, timeout=None):
        pass
    def __getattr__(self, name):
        return self


class MockMouse:
    def __init__(self, log):
        self._log = log
    def click(self, x, y):
        self._log(f"mouse.click({x:.0f}, {y:.0f})")


class MockPage:
    """
    Fake Playwright page.

    All locator().first.is_visible() calls return False so every Playwright
    selector falls through to the JS coordinate fallback — which also returns
    None (canvas / buttons not present in a dry run).

    The keyboard.type / keyboard.press calls are logged so we can read the
    exact action sequence.
    """

    def __init__(self):
        self._actions: list[str] = []
        self._step = 0

        def _log(msg):
            self._step += 1
            self._actions.append(f"  {self._step:>3}. {msg}")
            print(f"  {self._step:>3}. {msg}")

        self.keyboard = MockKeyboard(_log)
        self.mouse    = MockMouse(_log)
        self._log     = _log

    def locator(self, sel):
        # Return an object whose .first returns a MockLocator
        class _Loc:
            @property
            def first(self_inner):
                return MockLocator()
        return _Loc()

    def evaluate(self, *args, **kwargs):
        # JS coordinate scans return None (no buttons / canvas in dry run)
        return None

    def query_selector(self, *args):
        return None

    def wait_for_selector(self, *args, **kwargs):
        return None


# ── Import the real input layer AFTER patching time ───────────────────────────
from aleks_math_input import ALEKSInputLayer

# ── Test cases ────────────────────────────────────────────────────────────────

TEST_ANSWERS = [
    # (label, answer_string)
    ("Simple number",      "42"),
    ("Simple fraction",    "3/4"),
    ("Mixed number",       "2 3/5"),
    ("Square root",        "sqrt(16)"),
    ("Exponent",           "x^2"),
    ("Pi expression",      "pi"),
    ("Trig — simple arg",  "cos(x)"),
    ("Trig — pi/arg",      "-4cos(πt/4)"),          # ← the broken case
    ("Trig — fraction arg","sin(2πt/8)"),
    ("Composite",          "3/4 + sqrt(x^2-4)"),
]

logging.basicConfig(level=logging.WARNING)  # suppress internal logs for clarity


def run_simulation():
    page  = MockPage()
    layer = ALEKSInputLayer(page)

    HEADER = "\033[1;96m"
    RESET  = "\033[0m"
    DIM    = "\033[2m"
    WARN   = "\033[93m"

    for label, answer in TEST_ANSWERS:
        page._step    = 0
        page._actions = []

        print(f"\n{HEADER}{'─'*60}{RESET}")
        print(f"{HEADER}  Answer: {answer!r}   [{label}]{RESET}")
        print(f"{'─'*60}")

        # Show tokenizer output first
        tokens = layer._tokenize(answer.strip())
        print(f"{DIM}  Tokens: {tokens}{RESET}")
        print()

        # Simulate (no browser focus needed — skip it)
        layer._input_expression(answer.strip())

        if not page._actions:
            print(f"  {WARN}(no actions recorded){RESET}")

    print(f"\n{HEADER}{'═'*60}{RESET}")
    print(f"{HEADER}  SIMULATION COMPLETE{RESET}")
    print(f"{HEADER}{'═'*60}{RESET}\n")


if __name__ == "__main__":
    run_simulation()
    _time_patcher.stop()
