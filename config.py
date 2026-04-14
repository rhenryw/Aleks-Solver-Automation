"""
config.py — ALEKS AutoSolver configuration.
"""

# ─── ALEKS Credentials ─────────────────────────────────────────
ALEKS_URL = "https://www.aleks.com"
ALEKS_LOGIN_URL = "https://www.aleks.com/login"

# ─── Claude API ─────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 1024
CLAUDE_TEMPERATURE = 0.1  # Low = deterministic math answers

SYSTEM_PROMPT = (
    "You are a precise math solver. You receive a math problem extracted from ALEKS. "
    "Return ONLY the final answer in the exact format ALEKS expects:\n"
    "- For numerical answers: just the number (e.g., 3.14)\n"
    "- For fractions: use / (e.g., 3/4)\n"
    "- For multiple choice: just the letter (e.g., B)\n"
    "- For expressions: use standard notation (e.g., 2x + 3)\n"
    "- For graphing: return coordinates as JSON array\n"
    "No explanations, no steps, no words. ONLY the answer."
)

# ─── ALEKS Activities ───────────────────────────────────────────
# Add or remove activities as needed for your course
ACTIVITIES = {
    1:  "Activity 1 - Real numbers and the number line",
    2:  "Activity 2 - Order of operations",
    3:  "Activity 3 - Evaluating algebraic expressions",
    4:  "Activity 4 - Simplifying algebraic expressions",
    5:  "Activity 5 - Solving linear equations",
    6:  "Activity 6 - Graphing linear equations",
    7:  "Activity 7 - Systems of linear equations",
    8:  "Activity 8 - Quadratic equations and factoring",
    9:  "Activity 9 - Sine, cosine and tangent functions",
    10: "Activity 10 - Secant, cosecant and cotangent functions",
    11: "Activity 11 - Trigonometric identities",
    12: "Activity 12 - Graphs of trigonometric functions",
    13: "Activity 13 - Inverse trigonometric functions",
    14: "Activity 14 - Law of sines and cosines",
    15: "Activity 15 - Exponential and logarithmic functions",
    16: "Activity 16 - Sequences and series",
    17: "Activity 17 - Limits and continuity",
    18: "Activity 18 - Derivatives and differentiation",
    19: "Activity 19 - Integration and antiderivatives",
    20: "Activity 20 - Applications of integrals",
}

# ─── Browser Settings ───────────────────────────────────────────
HEADLESS = False          # Set True to run without visible browser
SLOW_MO = 800             # Milliseconds between actions (looks more human)
TIMEOUT = 30000           # Max wait for elements (ms)
SCREENSHOT_ON_ERROR = True
