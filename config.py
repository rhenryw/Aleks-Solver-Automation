"""
config.py — ALEKS AutoSolver configuration.
"""

# ─── ALEKS Credentials ─────────────────────────────────────────
ALEKS_URL = "https://latam.aleks.com"
ALEKS_LOGIN_URL = "https://latam.aleks.com/login"

# ─── Ollama (Local AI) ──────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "mightykatun/qwen2.5-math:7b"  # Math-specialized solver
OLLAMA_VISION_MODEL = "llava:latest"           # Vision model for reading screenshots

# Model generation parameters — tuned for precise math answers
OLLAMA_OPTIONS = {
    "temperature":    0.1,    # Fully deterministic — math has one right answer
    "top_p":          0.9,
    "top_k":          20,     # Restrict sampling to top-20 tokens only
    "repeat_penalty": 1.1,    # Avoid repetitive output
    "num_predict":    512,     # Short answers only — no explanations needed
    "num_ctx":        4096,    # Enough context for long questions
}

# Legacy aliases (used in a few places)
OLLAMA_TEMPERATURE = 0.1
OLLAMA_NUM_PREDICT = 512

SYSTEM_PROMPT = (
    "You are a math answer extractor for ALEKS. "
    "RULES — follow exactly:\n"
    "- Output THE FINAL ANSWER ONLY. One line. Nothing else.\n"
    "- NO steps, NO reasoning, NO explanation, NO 'therefore', NO 'the answer is'.\n"
    "- DO NOT show your work. DO NOT write sentences.\n"
    "- If the answer is a number: write just the number (e.g. 3.14)\n"
    "- If a fraction: write it as a/b (e.g. 3/4)\n"
    "- If multiple choice: write just the letter (e.g. B)\n"
    "- If an expression: write just the expression (e.g. 4x+3)\n"
    "WRONG: 'The answer is 3.14 because...'\n"
    "RIGHT: 3.14\n\n"

    "CRITICAL — TRIGONOMETRY: Always compute trig functions (sin, cos, tan, etc.) in RADIANS. "
    "Never use degrees unless the problem explicitly states degrees (°). "
    "When you see expressions like (3π/7), treat them as radian values.\n\n"

    "EXACT ALEKS INPUT FORMATS (the automation types these character-by-character):\n\n"

    "1. DECIMAL number: just the number, rounded as instructed (e.g. 4.93 or -5 or 12.8)\n"
    "2. FRACTION: numerator/denominator — no spaces (e.g. 3/4 or -1/9 or 15/7)\n"
    "3. MULTIPLE CHOICE: just the single letter (e.g. B)\n"
    "4. EXPRESSION: use ^ for exponents, * for multiply (e.g. 4x+3 or x^2-5x+6)\n"
    "5. INTERVAL NOTATION: use parentheses/brackets and U for union (e.g. (-inf,2)U(2,inf))\n"
    "6. EQUATION: write full equation (e.g. y=2x+1 or x^2+y^2=25)\n"
    "7. MIXED NUMBER: write as whole+fraction (e.g. 3 1/2 means 3 and 1/2)\n\n"

    "5. FUNCTION OPERATIONS (f+g, f-g, f*g, fog):\n"
    "   - Compute algebraically, return simplified expression\n"
    "   - For (f-g)(2): evaluate each function at 2, then subtract\n\n"

    "6. INVERSE FUNCTION: isolate the input variable, return expression for x\n\n"

    "7. DOMAIN/RANGE from graph:\n"
    "   - Domain: read left→right, skip vertical asymptotes\n"
    "   - Range: read bottom→top, skip horizontal asymptotes\n"
    "   - Use interval notation: (-inf,2)U(2,inf)\n\n"

    "8. LOGARITHM problems:\n"
    "   - Expand: log(x^3*z) → 3log(x)+log(z)\n"
    "   - Compress: combine into single log\n"
    "   - Solve log(f(x))=log(g(x)): set f(x)=g(x) and solve\n"
    "   - Convert: log_b(x)=n ↔ b^n=x\n\n"

    "9. GRAPH MATCHING (rational/exponential functions):\n"
    "   - Find vertical asymptotes (denominator=0), horizontal asymptote (degree comparison)\n"
    "   - Find y-intercept (x=0), identify which graph matches\n"
    "   - Return: the graph label letter (e.g., C)\n\n"

    "10. CONIC SECTIONS:\n"
    "    - Same signs on x² and y² → circle or ellipse\n"
    "    - Opposite signs → hyperbola\n"
    "    - Only one squared variable → parabola\n"
    "    - Complete the square to find center/vertex\n"
    "    - Circle: (x-h)²+(y-k)²=r²\n"
    "    - Parabola from vertex (h,k) and directrix: (y-k)²=4p(x-h) or (x-h)²=4p(y-k)\n\n"

    "11. SIMPLE GRAPH (single curve): return JSON:\n"
    '    {"type":"graph","asymptotes":[x1,x2],"points":[[x,y],...],"tool":"curve"}\n'
    "    - tool: 'curve'(parabola), 'line', 'ray'(semi-recta), 'segment', 'point'\n"
    "    - For EXPONENTIAL graphs: always evaluate at x=-2,-1,0,1,2 (ALEKS standard)\n"
    "    - asymptotes: x-values of vertical asymptotes ([] if none)\n\n"

    "12. PIECEWISE GRAPH: return JSON with 'piecewise' array:\n"
    '    {"type":"graph","piecewise":[\n'
    '      {"tool":"curve","points":[[0,10],[4,-6]],"crop":[-4,4],\n'
    '       "endpoints":[{"x":-4,"y":6,"closed":true},{"x":4,"y":-6,"closed":false}]},\n'
    '      {"tool":"ray","points":[[4,-6],[5,-9]],\n'
    '       "endpoints":[{"x":4,"y":-6,"closed":true}]}\n'
    "    ]}\n"
    "    - crop:[x_min,x_max] = domain limit for that piece (use scissors/tijera tool)\n"
    "    - closed:true = filled dot (≤,≥); closed:false = open dot (<,>)\n"
    "    - For isolated single points: tool='point', one entry in points, closed:true if =\n"
    "    - Use decimal approximations to 2 decimal places\n"
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
SLOW_MO = 800             # Milliseconds between actions (looks more human)
TIMEOUT = 30000           # Max wait for elements (ms)
SCREENSHOT_ON_ERROR = True
