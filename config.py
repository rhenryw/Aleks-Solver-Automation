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

# ─── ALEKS Activities (by Semester) ─────────────────────────────
# Each semester maps activity numbers → activity names.
# Edit these to match your actual ALEKS course topics.

SEMESTER_1_ACTIVITIES = {
    1:  "Activity 1 - Whole numbers and integers",
    2:  "Activity 2 - Fractions and mixed numbers",
    3:  "Activity 3 - Decimals and percents",
    4:  "Activity 4 - Ratios and proportions",
    5:  "Activity 5 - Introduction to variables and expressions",
    6:  "Activity 6 - Solving one-step equations",
    7:  "Activity 7 - Solving two-step equations",
    8:  "Activity 8 - Inequalities on the number line",
    9:  "Activity 9 - Introduction to geometry (angles and lines)",
    10: "Activity 10 - Perimeter, area and volume",
    11: "Activity 11 - Mean, median and mode",
    12: "Activity 12 - Introduction to probability",
    13: "Activity 13 - Reading graphs and tables",
    14: "Activity 14 - Unit conversions",
    15: "Activity 15 - Word problems with whole numbers",
}

SEMESTER_2_ACTIVITIES = {
    1:  "Activity 1 - Real numbers and the number line",
    2:  "Activity 2 - Order of operations",
    3:  "Activity 3 - Evaluating algebraic expressions",
    4:  "Activity 4 - Simplifying algebraic expressions",
    5:  "Activity 5 - Solving linear equations",
    6:  "Activity 6 - Graphing linear equations",
    7:  "Activity 7 - Systems of linear equations",
    8:  "Activity 8 - Polynomials and factoring",
    9:  "Activity 9 - Quadratic equations",
    10: "Activity 10 - Rational expressions",
    11: "Activity 11 - Radical expressions and equations",
    12: "Activity 12 - Functions and function notation",
    13: "Activity 13 - Exponential and logarithmic functions",
    14: "Activity 14 - Compound and simple interest",
    15: "Activity 15 - Linear inequalities and systems",
    16: "Activity 16 - Introduction to statistics",
    17: "Activity 17 - Scatter plots and correlation",
    18: "Activity 18 - Probability and counting",
}

SEMESTER_3_ACTIVITIES = {
    1:  "Activity 1 - Sine, cosine and tangent functions",
    2:  "Activity 2 - Secant, cosecant and cotangent functions",
    3:  "Activity 3 - Trigonometric identities",
    4:  "Activity 4 - Graphs of trigonometric functions",
    5:  "Activity 5 - Inverse trigonometric functions",
    6:  "Activity 6 - Law of sines and cosines",
    7:  "Activity 7 - Polar coordinates and complex numbers",
    8:  "Activity 8 - Vectors in two dimensions",
    9:  "Activity 9 - Conic sections",
    10: "Activity 10 - Sequences and series",
    11: "Activity 11 - Limits and continuity",
    12: "Activity 12 - Derivatives and differentiation",
    13: "Activity 13 - Applications of derivatives",
    14: "Activity 14 - Integration and antiderivatives",
    15: "Activity 15 - Applications of integrals",
    16: "Activity 16 - Differential equations (intro)",
    17: "Activity 17 - Parametric equations",
    18: "Activity 18 - Matrices and determinants",
    19: "Activity 19 - Binomial theorem",
    20: "Activity 20 - Mathematical induction and proofs",
}

SEMESTER_4_ACTIVITIES = {
    1:  "Activity 1 - Multivariable functions",
    2:  "Activity 2 - Partial derivatives",
    3:  "Activity 3 - Gradient and directional derivatives",
    4:  "Activity 4 - Multiple integrals",
    5:  "Activity 5 - Vector calculus",
    6:  "Activity 6 - Line and surface integrals",
    7:  "Activity 7 - Green's, Stokes' and divergence theorems",
    8:  "Activity 8 - First-order differential equations",
    9:  "Activity 9 - Second-order differential equations",
    10: "Activity 10 - Laplace transforms",
    11: "Activity 11 - Systems of differential equations",
    12: "Activity 12 - Power series solutions",
    13: "Activity 13 - Vector spaces and subspaces",
    14: "Activity 14 - Linear transformations",
    15: "Activity 15 - Eigenvalues and eigenvectors",
    16: "Activity 16 - Orthogonality and least squares",
    17: "Activity 17 - Matrix decompositions (LU, QR, SVD)",
    18: "Activity 18 - Complex analysis (intro)",
    19: "Activity 19 - Fourier series",
    20: "Activity 20 - Numerical methods",
}

# Semester selector — maps semester number → (label, activities dict)
SEMESTERS = {
    1: ("1st Semester — Foundations", SEMESTER_1_ACTIVITIES),
    2: ("2nd Semester — Intermediate Algebra", SEMESTER_2_ACTIVITIES),
    3: ("3rd Semester — Precalculus & Calculus", SEMESTER_3_ACTIVITIES),
    4: ("4th Semester — Advanced Calculus & Linear Algebra", SEMESTER_4_ACTIVITIES),
}

# Default semester (overridden at runtime by user selection in main.py)
SEMESTER = 1
ACTIVITIES = SEMESTERS[SEMESTER][1]


# ─── Browser Settings ───────────────────────────────────────────
HEADLESS = False          # Set True to run without visible browser
SLOW_MO = 800             # Milliseconds between actions (looks more human)
TIMEOUT = 30000           # Max wait for elements (ms)
SCREENSHOT_ON_ERROR = True
