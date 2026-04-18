"""
config.py — ALEKS AutoSolver configuration.
"""

# ─── ALEKS Credentials ─────────────────────────────────────────
ALEKS_URL = "https://latam.aleks.com"
ALEKS_LOGIN_URL = "https://latam.aleks.com/login"

SYSTEM_PROMPT = """\
You are an ALEKS math solver. Analyze the screenshot and return ONLY a JSON object describing the answer.
No explanation, no steps, no markdown code fences — just the raw JSON object.

ANSWER FORMAT RULES (pick the type that matches the answer):

1. Simple number, variable, or plain expression:
   {"type": "simple", "value": "42"}
   {"type": "simple", "value": "-3.5"}
   {"type": "simple", "value": "x + 3"}
   {"type": "simple", "value": "x > 3"}
   {"type": "simple", "value": "[-2, 5)"}

2. Fraction (a/b):
   {"type": "fraction", "numerator": "3", "denominator": "4"}

3. Square root:
   {"type": "sqrt", "radicand": "16"}
   {"type": "sqrt", "radicand": "x + 4"}

4. Exponent (base^exp):
   {"type": "exponent", "base": "x", "exponent": "2"}
   {"type": "exponent", "base": "2", "exponent": "n+1"}

5. Mixed number (whole + fraction):
   {"type": "mixed", "whole": "2", "numerator": "3", "denominator": "5"}

6. Complex expression combining multiple operations — use expression notation:
   {"type": "expression", "value": "3/4 + sqrt(x^2 - 4)"}
   {"type": "expression", "value": "2*pi*sqrt(5)"}
   Notation rules for expression values:
     / for fractions, sqrt(...) for roots, ^ for exponents,
     pi for π, sin/cos/tan for trig, | | for absolute value

7. Graph (plot points on a coordinate grid):
   {"type": "graph", "points": [[x1, y1], [x2, y2]]}
   Include key points: intercepts, vertices, turning points, endpoints.
   For a line: provide exactly 2 points on that line.
   For a parabola/curve: provide 3–5 key points.

IMPORTANT:
- If the answer is just a single integer like 5, output: {"type": "simple", "value": "5"}
- If the answer contains a fraction AND other terms, use type "expression"
- Always use standard decimal notation for decimals (e.g. "0.75" not "75/100")
- For trig: sin(x), cos(x), tan(x) — use parentheses
- For pi: write "pi" (not "3.14159")
"""

# ─── Chatbot Browser Tab (auto-mcgraw approach) ─────────────────
# The script opens ChatGPT/Gemini/DeepSeek in a browser tab.
# You must be logged in to the provider before running.
CHATBOT_PROVIDER = "gemini"    # "chatgpt" | "gemini" | "deepseek"

# ─── Humanization Delay ────────────────────────────────────────
# Random pause (seconds) inserted between solver returning an answer
# and the browser submitting it.  Looks more human, avoids detection.
HUMANIZE_DELAY_MIN = 0.5   # seconds
HUMANIZE_DELAY_MAX = 0.5   # seconds

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

# ─── Auto-Detect Semester from Class Name ───────────────────────
# Maps keywords/substrings found in ALEKS class names → semester number.
# The first matching pattern wins. Case-insensitive.
# ⚠️  Customize these to match YOUR actual ALEKS class names!
CLASS_SEMESTER_PATTERNS = {
    # Spanish patterns
    "1er semestre": 1, "semestre 1": 1, "primer semestre": 1,
    "2do semestre": 2, "semestre 2": 2, "segundo semestre": 2,
    "3er semestre": 3, "semestre 3": 3, "tercer semestre": 3,
    "4to semestre": 4, "semestre 4": 4, "cuarto semestre": 4,
    # English patterns
    "semester 1": 1, "1st semester": 1,
    "semester 2": 2, "2nd semester": 2,
    "semester 3": 3, "3rd semester": 3,
    "semester 4": 4, "4th semester": 4,
    # Topic-based patterns
    "foundations": 1, "fundamentos": 1,
    "intermediate algebra": 2, "álgebra intermedia": 2, "algebra intermedia": 2,
    "precalcul": 3, "precálcul": 3, "trigonometr": 3,
    "advanced calculus": 4, "linear algebra": 4, "álgebra lineal": 4,
    "cálculo avanzado": 4, "calculo avanzado": 4,
}


# ─── Browser Settings ───────────────────────────────────────────
HEADLESS = False          # Set True to run without visible browser
SLOW_MO = 50              # Milliseconds between actions (looks more human)
TIMEOUT = 30000           # Max wait for elements (ms)
SCREENSHOT_ON_ERROR = True
