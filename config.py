"""
config.py — ALEKS AutoSolver configuration.

Only non-secret settings live here. API keys/endpoints come from the
environment (see .env.example) or are overridden at runtime.
"""

# ─── ALEKS URLs ─────────────────────────────────────────────────
ALEKS_HOME_URL  = "https://www.aleks.com/student/home"
ALEKS_LOGIN_URL = "https://www.aleks.com/login"


# ─── Real ALEKS selectors (captured via record_session.py) ──────
# These IDs are stable across ALEKS courses as of 2026.
SELECTORS = {
    # Home / dashboard
    "start_learning":    "#smt_bottomnav_button_input_start_learning",

    # Problem page — bottom-nav buttons.
    # `continue_learning` / `try_again` share the same ID — the button's
    # label changes ("Start", "Continue My Path", "Try Again") but the
    # underlying action is always "advance past the current state".
    "check_answer":      "#smt_bottomnav_button_input_checkAnswer",
    "next_correct":      "#smt_bottomnav_button_input_learningCorrect",
    "new_item":          "#smt_bottomnav_button_input_newItem",
    "continue_learning": "#smt_bottomnav_button_input_learning",
    "try_again":         "#smt_bottomnav_button_input_learning",

    # "Explain" / secondary action buttons
    "secondary_button":  "button[id$='_secondary_button']",

    # Answer editor ("ansed" = answer editor). Inputs come in a few flavors:
    #   ansed_input_ansed…       — single math input (most problems)
    #   ansed_input_tabed…       — labeled boxes inside a <table>
    #                              (e.g. "Degree: __  Leading coefficient: __")
    #   ansed_input_mced…        — multiple-choice style
    "ansed_root":        "[id^='ansed_root_']",
    "ansed_tree":        ".ansed_tree",
    "ansed_input":       "[id^='ansed_input_']",

    # Iframes — ALEKS embeds problems in iframes sometimes
    "problem_iframe":    "iframe[id^='iframe'], iframe[name*='problem'], iframe[src*='alekscgi']",

    # Graph / number-line editor ("figed" = figure editor).
    # The click surface and its four toolbar buttons (open dot, closed dot,
    # interval, eraser). IDs include a run-specific suffix after "figed_I"
    # so we match the common prefix / suffix instead.
    "figed_root":        "[id^='figed_I']",
    "figed_label":       "[id^='label_figed_figed']",
    "figed_surface":     "[id^='figed_events_']",
    "figed_open":        "[id*='_figed_lineopen']",
    "figed_closed":      "[id*='_figed_lineclose']",
    "figed_interval":    "[id*='_figed_lineinterval']",
    "figed_eraser":      "[id*='_figed_eraser']",
    "figed_reset":       "[id*='_figed_reset']",
    "ansed_reset":       "[id*='_ansed_reset']",
}

# URL fragments on ALEKS indicating current page state
URL_FRAGMENT_HOME = "#home"
URL_FRAGMENT_ITEM = "#item"    # a problem is currently shown


# ─── AI (OpenAI-compatible) ─────────────────────────────────────
# Overridden by env: OPENAI_BASE_URL, OPENAI_API_KEY, AI_MODEL
MODEL       = "gpt-4o"
MAX_TOKENS  = 2048
TEMPERATURE = 0.1

SYSTEM_PROMPT = (
    "You are a precise math solver. You receive a math problem extracted from ALEKS. "
    "Return ONLY the final answer in the exact format ALEKS expects:\n"
    "- ALWAYS simplify your answer as much as possible unless the problem "
    "explicitly says otherwise. Reduce fractions to lowest terms "
    "(e.g. 6/8 → 3/4, 10/-4 → -5/2). Combine like terms. Rationalize "
    "denominators (sqrt(2)/2, not 1/sqrt(2)). Simplify radicals by "
    "pulling out perfect-power factors (sqrt(50) → 5*sqrt(2), "
    "root(3,54) → 3*root(3,2)). Reduce exponents (x^2*x^3 → x^5). "
    "Give exact values, not decimal approximations, unless the problem "
    "asks to 'round to N decimal places'.\n"
    "- For EQUATIONS solved for a variable (e.g. 'Solve for x. 3 = 18x − 6y'): "
    "do NOT prefix with 'x =' — ALEKS shows the variable label; give only the RHS "
    "(answer '(3+6y)/18', NOT 'x = (3+6y)/18').\n"
    "- For INEQUALITIES (problems that say 'Solve the inequality'): DO include the "
    "full relation with the variable. Examples: 'x<=4', 'x>-3', 'y>=1/2'. Use the "
    "ASCII operators <=, >=, <, > (never ≤/≥ or words). The ALEKS answer widget has "
    "a two-slot template that needs both the variable AND the bound.\n"
    "- For numerical answers: just the number (e.g., 3.14)\n"
    "- For fractions: use / (e.g., 3/4). Always parenthesise the numerator and "
    "denominator when either is a sum/difference (e.g., (3+6y)/18, NOT 3+6y/18).\n"
    "- For exponents: use ^ (e.g., x^2 + 2*x*y + y^2)\n"
    "- For square roots: use sqrt(...) with parentheses around the entire radicand "
    "(e.g., 5*sqrt(6), sqrt(2)/2, 4*sqrt(7)). Never use √ or \\sqrt.\n"
    "- For nth roots: use root(n, x) (e.g., root(3, 8) for cube root of 8).\n"
    "- For multiplication: always use * between a coefficient and a radical "
    "or variable (e.g., 5*sqrt(6), not 5sqrt(6)).\n"
    "- For multiple choice: just the letter (e.g., B)\n"
    "- For expressions: use standard notation (e.g., 2x + 3)\n"
    "- For problems with MULTIPLE answer boxes on the same screen (e.g. "
    "'Degree: __  Leading coefficient: __', or two evaluations like "
    "'216^(1/3) = __' and '16^(1/4) = __', or 'x = __, y = __'): return "
    "the answers in order, separated by commas with no spaces. "
    "Examples: '6,-1' for (degree=6, coeff=-1); '6,2' for the two evaluations; "
    "'3,-2' for (x=3, y=-2). Do NOT include labels or variable names.\n"
    "- For graphing questions: return a JSON object with this EXACT format:\n"
    '  {"type":"graph","asymptotes":[-3.14,0,3.14],"points":[[1.57,1],[-1.57,-1]],"tool":"curve"}\n'
    "- For number-line / inequality problems (\"graph the inequality on the number "
    "line\"), return a JSON object with this EXACT format:\n"
    '  {"type":"numberline","points":[{"x":-1,"open":true},{"x":7,"open":true}],'
    '"segments":[{"from":-1,"to":7}]}\n'
    '  Use "open":true for strict (< or >) and "open":false for inclusive (≤ or ≥). '
    'For rays to infinity use "from":3,"to":"+inf" or "from":"-inf","to":-2. '
    'For "x ≥ a AND x ≤ b" create a single segment from a to b. '
    'For "x < a OR x > b" create two separate rays.\n'
    '- If the problem ALSO asks for interval notation (e.g. "Graph the set '
    '{x | -5 ≤ x ≤ -2} on the number line. Then, write the set using interval '
    'notation."), include an "interval" field in the same JSON. Format: '
    '{"type":"numberline","points":[...],"segments":[...],'
    '"interval":"[-5,-2]"}. Use "[" or "]" for inclusive, "(" or ")" for '
    'exclusive, "-inf" / "+inf" for rays, "empty" for the empty set. '
    'Use "U" between disjoint pieces, e.g. "(-inf,-3)U(2,+inf)".\n'
    "No explanations, no steps, no words. ONLY the answer."
)


# ─── Browser behavior ───────────────────────────────────────────
HEADLESS            = False
SLOW_MO             = 250      # ms between actions
TIMEOUT             = 30_000   # default element wait (ms)
SCREENSHOT_ON_ERROR = True


# ─── Solver behavior ────────────────────────────────────────────
MAX_QUESTIONS_PER_SESSION = 100   # safety cap
MAX_WRONG_ATTEMPTS        = 2     # tries per problem before clicking "Try Again"
WAIT_AFTER_CHECK_SECONDS  = 1.5   # wait after clicking Check for grading
WAIT_AFTER_NEXT_SECONDS   = 2.0   # wait after advancing to next problem
