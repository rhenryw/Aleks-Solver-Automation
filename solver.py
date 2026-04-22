"""
solver.py — OpenAI-compatible API solver with confirmed-answer caching.

Token efficiency:
  1. Questions are extracted as TEXT from the browser (0 tokens for reading)
    2. SHA-256 cache prevents duplicate API calls
  3. Minimal prompt: system instruction + question only
  4. Low max_tokens since answers are short

Environment variables:
  OPENAI_API_KEY   — required; your API key
  OPENAI_BASE_URL  — optional; defaults to https://api.openai.com/v1
  AI_MODEL         — optional; overrides config.MODEL
"""

import hashlib
import json
import os
import logging
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

try:
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        parse_expr,
        standard_transformations,
        implicit_multiplication_application,
    )
except Exception:
    sp = None
    parse_expr = None
    standard_transformations = ()
    implicit_multiplication_application = None

import config

load_dotenv()  # load .env if present

log = logging.getLogger("solver")


class Solver:
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "Missing OPENAI_API_KEY. Set it before running:\n"
                '  export OPENAI_API_KEY="your-key-here"   (Linux/Mac)\n'
                '  set OPENAI_API_KEY=your-key-here         (CMD)\n'
                '  $env:OPENAI_API_KEY="your-key-here"      (PowerShell)\n'
                "Or put it in a .env file in the project root."
            )

        base_url = os.environ.get("OPENAI_BASE_URL")  # None → SDK uses default
        self.model = os.environ.get("AI_MODEL") or config.MODEL

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.tokens_used = 0
        self.cache_hits = 0
        self.api_calls = 0

        # Load cache (confirmed-only schema).
        # Legacy cache files stored raw strings that might include wrong
        # answers; those are intentionally ignored.
        self.cache_path = Path("answer_cache.json")
        self.cache: dict[str, str] = {}
        if self.cache_path.exists():
            try:
                raw = json.loads(self.cache_path.read_text())
            except Exception:
                raw = {}

            if isinstance(raw, dict) and raw.get("_format") == "confirmed-only-v2":
                entries = raw.get("answers", {})
                if isinstance(entries, dict):
                    for k, v in entries.items():
                        if (isinstance(v, dict)
                                and v.get("confirmed") is True
                                and isinstance(v.get("answer"), str)
                                and v["answer"].strip()):
                            self.cache[k] = v["answer"].strip()
            log.info(f"Loaded {len(self.cache)} confirmed cached answers")

    def _hash(self, question: str) -> str:
        return hashlib.sha256(question.strip().lower().encode()).hexdigest()[:16]

    def _save_cache(self):
        payload = {
            "_format": "confirmed-only-v2",
            "answers": {
                k: {"answer": v, "confirmed": True}
                for k, v in self.cache.items()
            },
        }
        self.cache_path.write_text(json.dumps(payload, indent=2))

    def _chat(self, messages, max_tokens: int, temperature: float):
        """
        Call chat.completions with automatic fallbacks for model/endpoint
        quirks: some newer models require `max_completion_tokens` instead of
        `max_tokens`, and some reject non-default `temperature`.
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            return self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            # Older endpoints don't know about max_completion_tokens
            if "max_completion_tokens" in msg and "unsupported" in msg:
                kwargs.pop("max_completion_tokens", None)
                kwargs["max_tokens"] = max_tokens
                return self.client.chat.completions.create(**kwargs)
            # Some models only accept the default temperature
            if "temperature" in msg and ("unsupported" in msg or "does not support" in msg):
                kwargs.pop("temperature", None)
                return self.client.chat.completions.create(**kwargs)
            raise

    @staticmethod
    def _extract_answer(raw: str) -> str:
        """Parse model output and return a single ALEKS-ready answer string."""
        raw = (raw or "").strip()
        answer = raw

        # Prefer explicit ANSWER: line.
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"(?i)^\**\s*answer\s*[:=]\s*(.+?)\**\s*$", line)
            if m:
                answer = m.group(1).strip()
                break
        else:
            # Fallback: last non-empty line.
            for line in reversed(raw.splitlines()):
                if line.strip():
                    answer = line.strip()
                    break

        # Strip wrappers and trailing sentence punctuation.
        answer = answer.strip("`\"' ")
        answer = re.sub(r"[;:!?]+$", "", answer).strip()

        # "16." -> "16" (keep real decimals like 3.14)
        if re.fullmatch(r"[+-]?\d+\.", answer):
            answer = answer[:-1]
        elif re.fullmatch(r"[A-Za-z]\s*[<>]=?\s*[+-]?\d+\.", answer):
            answer = answer[:-1]

        return answer

    @staticmethod
    def _is_invalid_answer(answer: str) -> bool:
        """Detect unusable outputs that should never be typed into ALEKS."""
        a = (answer or "").strip()
        if not a:
            return True
        # punctuation-only outputs like '.', ',', '...'
        if re.fullmatch(r"[\.,;:!?'\-_=+()\[\]{}]+", a):
            return True
        return False

    def _solve_symbolically(self, question: str) -> str | None:
        """
        Deterministic fallback for algebra templates that are easy to parse.
        Returns an ALEKS-ready answer string, or None when not applicable.
        """
        if sp is None or parse_expr is None:
            return None

        q = (question or "").strip()

        # Pattern: "Rationalize the denominator ..."
        m = re.search(r"(?is)\brational(?:iz)?e\s+(?:the\s+)?denominator", q)
        if m:
            # Extract the expression (find fractions or raw math text).
            # Strategy: look for the expression after "Rationalize" or in the whole Q.
            expr_text = q
            # Remove instruction text to isolate the math.
            expr_text = re.sub(r"(?is)rationali[sz]e\s+(?:the\s+)?denominator(?:\s+and\s+simplify)?[.:]?", "", expr_text)
            expr_text = expr_text.strip()
            if expr_text:
                try:
                    # Normalize Unicode characters before parsing.
                    t = expr_text.replace("−", "-")  # Unicode minus → ASCII
                    # Handle √: convert √2 to sqrt(2), √(expr) to sqrt(expr)
                    t = re.sub(r"√\(([^)]+)\)", r"sqrt(\1)", t)  # √(expr) -> sqrt(expr)
                    t = re.sub(r"√(\d+)", r"sqrt(\1)", t)  # √2 -> sqrt(2)
                    # Parse and rationalize using SymPy's simplify.
                    t = t.replace("^", "**")
                    transformations = standard_transformations + (implicit_multiplication_application,)
                    expr = parse_expr(t, transformations=transformations, evaluate=True)
                    # Rationalize + simplify, then extract as single fraction.
                    simp = sp.together(sp.simplify(expr))
                    numer, denom = sp.fraction(simp)
                    numer_exp = sp.expand(numer)
                    # Format as (numerator)/(denominator)
                    numer_str = sp.sstr(numer_exp).replace("**", "^")
                    denom_str = sp.sstr(denom).replace("**", "^")
                    numer_str = re.sub(r"\s+", "", numer_str)
                    denom_str = re.sub(r"\s+", "", denom_str)
                    # Remove * only between digit and single-letter variable (e.g., 3*x → 3x), not before functions
                    numer_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", numer_str)
                    denom_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", denom_str)
                    out = f"({numer_str})/({denom_str})"
                    if out:
                        log.info(f"  Symbolic rationalization: {out}")
                        return out
                except Exception as e:
                    log.debug(f"  Rationalization parse failed: {e}")

        # Pattern: "Add. ... Simplify ..." or "Subtract. ... Simplify ..."
        m = re.search(r"(?is)\b(add|subtract)\.\s*(.+?)(?:\s+simplify\b|$)", q)
        if m:
            expr_text = m.group(2).strip()
            if expr_text:
                try:
                    # SymPy parser: allow implicit multiplication (e.g. "3 x").
                    t = expr_text.replace("^", "**")
                    transformations = standard_transformations + (implicit_multiplication_application,)
                    expr = parse_expr(t, transformations=transformations, evaluate=True)
                    simp = sp.together(sp.simplify(expr))
                    out = sp.sstr(simp)
                    out = out.replace("**", "^")
                    out = re.sub(r"\s+", "", out)
                    if out:
                        return out
                except Exception:
                    pass

        # Pattern: Standalone "Simplify." (likely complex fractions or rational expressions)
        m = re.search(r"(?is)^simplify\.\s*(.+?)(?:simplify\s+your|$)", q)
        if m:
            expr_text = m.group(1).strip()
            if expr_text:
                try:
                    # Normalize Unicode.
                    t = expr_text.replace("−", "-")
                    t = t.replace("·", "*")
                    t = re.sub(r"√\(([^)]+)\)", r"sqrt(\1)", t)
                    t = re.sub(r"√(\d+)", r"sqrt(\1)", t)
                    # Parse and simplify.
                    t = t.replace("^", "**")
                    transformations = standard_transformations + (implicit_multiplication_application,)
                    expr = parse_expr(t, transformations=transformations, evaluate=True)
                    # Use cancel for complex fractions, simplify for other expressions.
                    simp = sp.cancel(sp.simplify(expr))
                    numer, denom = sp.fraction(simp)
                    numer_str = sp.sstr(numer).replace("**", "^")
                    denom_str = sp.sstr(denom).replace("**", "^")
                    numer_str = re.sub(r"\s+", "", numer_str)
                    denom_str = re.sub(r"\s+", "", denom_str)
                    # Remove * only between digit and single-letter variable.
                    numer_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", numer_str)
                    denom_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", denom_str)
                    out = f"({numer_str})/({denom_str})"
                    if out and out != "(1)/(1)":
                        log.info(f"  Symbolic simplify: {out}")
                        return out
                except Exception as e:
                    log.debug(f"  Simplify parse failed: {e}")

        # Pattern: "Multiply. ... Simplify ..."
        m = re.search(r"(?is)\bmultiply\.\s*(.+?)(?:\s+simplify\b|$)", q)
        if m:
            expr_text = m.group(1).strip()
            if expr_text:
                try:
                    # Normalize Unicode.
                    t = expr_text.replace("−", "-")  # Unicode minus
                    t = t.replace("·", "*")  # Middle dot multiplication
                    t = re.sub(r"√\(([^)]+)\)", r"sqrt(\1)", t)  # √(expr)
                    t = re.sub(r"√(\d+)", r"sqrt(\1)", t)  # √2
                    # Parse and cancel common factors.
                    t = t.replace("^", "**")
                    transformations = standard_transformations + (implicit_multiplication_application,)
                    expr = parse_expr(t, transformations=transformations, evaluate=True)
                    # Multiply and cancel (simplify fractions by factoring & canceling).
                    simp = sp.cancel(expr)
                    # Extract numerator and denominator for output.
                    numer, denom = sp.fraction(simp)
                    numer_str = sp.sstr(numer).replace("**", "^")
                    denom_str = sp.sstr(denom).replace("**", "^")
                    numer_str = re.sub(r"\s+", "", numer_str)
                    denom_str = re.sub(r"\s+", "", denom_str)
                    # Remove * only between digit and single-letter variable (e.g., 3*x → 3x), not before functions
                    numer_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", numer_str)
                    denom_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", denom_str)
                    out = f"({numer_str})/({denom_str})"
                    if out and out != "(1)/(1)":
                        log.info(f"  Symbolic multiply: {out}")
                        return out
                except Exception as e:
                    log.debug(f"  Multiply parse failed: {e}")

        # If no Add/Subtract/Multiply pattern matched, check "Solve for".
        # Pattern: Equivalent fractions with missing numerator/denominator.
        # E.g. "Fill in the blank: -6/(5v+6) = ?/(15v+18)"
        # Detect by looking for fractions with ? or blank in question, then equations.
        if "?" in q or "__" in q or "blank" in q.lower():
            try:
                def strip_outer_parens(s: str) -> str:
                    s = (s or "").strip()
                    while s.startswith("(") and s.endswith(")"):
                        depth = 0
                        ok = True
                        for i, ch in enumerate(s):
                            if ch == "(":
                                depth += 1
                            elif ch == ")":
                                depth -= 1
                                if depth < 0:
                                    ok = False
                                    break
                                if depth == 0 and i != len(s) - 1:
                                    ok = False
                                    break
                        if not ok:
                            break
                        s = s[1:-1].strip()
                    return s

                def split_top_level_fraction(s: str) -> tuple[str, str] | None:
                    s = (s or "").strip()
                    if not s:
                        return None
                    depth = 0
                    slash_at = -1
                    for i, ch in enumerate(s):
                        if ch == "(":
                            depth += 1
                        elif ch == ")":
                            depth = max(0, depth - 1)
                        elif ch == "/" and depth == 0:
                            slash_at = i
                            break
                    if slash_at <= 0 or slash_at >= len(s) - 1:
                        return None
                    num = strip_outer_parens(s[:slash_at])
                    den = strip_outer_parens(s[slash_at + 1:])
                    if not num or not den:
                        return None
                    return num, den

                eq_match = re.search(r"(.+?)=(.+)", q)
                if eq_match:
                    left_side = eq_match.group(1).strip()
                    right_side = eq_match.group(2).strip()

                    # Drop leading prose from each side; keep the math tail.
                    # Example:
                    # "Fill in the blank ... . (8 v)/(4 v - 7)"
                    # -> "(8 v)/(4 v - 7)"
                    if "." in left_side:
                        left_side = left_side.split(".")[-1].strip()
                    if "." in right_side:
                        right_side = right_side.split(".")[-1].strip()

                    prose = re.compile(
                        r"(?i)\b(fill\s+in\s+the\s+blank|to\s+make|equivalent|rational|expressions?)\b"
                    )
                    left_side = prose.sub(" ", left_side)
                    right_side = prose.sub(" ", right_side)
                    left_side = re.sub(r"\s+", " ", left_side).strip()
                    right_side = re.sub(r"\s+", " ", right_side).strip()

                    left_frac = split_top_level_fraction(left_side)
                    right_frac = split_top_level_fraction(right_side)
                else:
                    left_frac = right_frac = None

                if left_frac and right_frac:
                    n1_text, d1_text = left_frac
                    n2_text, d2_text = right_frac
                    
                    # Find which part is missing (contains ?, __, blank, or is empty)
                    n1_missing = any(x in n1_text for x in ["?", "__"]) or not n1_text or "blank" in n1_text.lower()
                    n2_missing = any(x in n2_text for x in ["?", "__"]) or not n2_text or "blank" in n2_text.lower()
                    d1_missing = any(x in d1_text for x in ["?", "__"]) or not d1_text or "blank" in d1_text.lower()
                    d2_missing = any(x in d2_text for x in ["?", "__"]) or not d2_text or "blank" in d2_text.lower()
                    
                    # Normalize the non-missing parts
                    def parse_expr_safe(text):
                        t = text.replace("−", "-").replace("·", "*")
                        t = re.sub(r"√\(([^)]+)\)", r"sqrt(\1)", t)
                        t = re.sub(r"√(\d+)", r"sqrt(\1)", t)
                        t = t.replace("^", "**")
                        transformations = standard_transformations + (implicit_multiplication_application,)
                        return parse_expr(t, transformations=transformations, evaluate=True)
                    
                    # Cross-multiply: n1/d1 = n2/d2 => n1*d2 = n2*d1
                    # Solve for the missing value
                    if n2_missing:
                        # Missing numerator: n1*d2 = ?*d1 => ? = n1*d2/d1
                        n1 = parse_expr_safe(n1_text)
                        d1 = parse_expr_safe(d1_text)
                        d2 = parse_expr_safe(d2_text)
                        answer = sp.simplify(n1 * d2 / d1)
                        answer_str = sp.sstr(answer).replace("**", "^")
                        answer_str = re.sub(r"\s+", "", answer_str)
                        answer_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", answer_str)
                        if answer_str:
                            log.info(f"  Symbolic equiv fracs (missing numerator): {answer_str}")
                            return answer_str
                    elif d2_missing:
                        # Missing denominator: n1*? = n2*d1 => ? = n2*d1/n1
                        n1 = parse_expr_safe(n1_text)
                        n2 = parse_expr_safe(n2_text)
                        d1 = parse_expr_safe(d1_text)
                        answer = sp.simplify(n2 * d1 / n1)
                        answer_str = sp.sstr(answer).replace("**", "^")
                        answer_str = re.sub(r"\s+", "", answer_str)
                        answer_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", answer_str)
                        if answer_str:
                            log.info(f"  Symbolic equiv fracs (missing denominator): {answer_str}")
                            return answer_str
                    elif n1_missing:
                        # Missing numerator on left: ?*d2 = n2*d1 => ? = n2*d1/d2
                        n2 = parse_expr_safe(n2_text)
                        d1 = parse_expr_safe(d1_text)
                        d2 = parse_expr_safe(d2_text)
                        answer = sp.simplify(n2 * d1 / d2)
                        answer_str = sp.sstr(answer).replace("**", "^")
                        answer_str = re.sub(r"\s+", "", answer_str)
                        answer_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", answer_str)
                        if answer_str:
                            log.info(f"  Symbolic equiv fracs (missing numerator): {answer_str}")
                            return answer_str
                    elif d1_missing:
                        # Missing denominator on left: n1*? = n2*d2 => ? = n2*d2/n1
                        n1 = parse_expr_safe(n1_text)
                        n2 = parse_expr_safe(n2_text)
                        d2 = parse_expr_safe(d2_text)
                        answer = sp.simplify(n2 * d2 / n1)
                        answer_str = sp.sstr(answer).replace("**", "^")
                        answer_str = re.sub(r"\s+", "", answer_str)
                        answer_str = re.sub(r"(\d)\*([a-z])(?![a-z])", r"\1\2", answer_str)
                        if answer_str:
                            log.info(f"  Symbolic equiv fracs (missing denominator): {answer_str}")
                            return answer_str
            except Exception as e:
                log.debug(f"  Equiv fracs parse failed: {e}")

        # Pattern: "Solve for v ... <equation>" (real-domain solutions).
        m_var = re.search(r"(?i)\bsolve\s+for\s+([a-z])\b", q)
        if m_var:
            var_name = m_var.group(1)
            eq_text = q

            # Keep only the part before answer-format instructions.
            eq_text = re.split(r"(?i)\bif\s+there\s+is\b|\bsimplify\b", eq_text)[0]

            # Remove common prose wrappers.
            eq_text = re.sub(rf"(?i)\bsolve\s+for\s+{var_name}\b", " ", eq_text)
            eq_text = re.sub(r"(?i)\bwhere\b[^=]*", " ", eq_text)

            # Normalize math text for parser.
            eq_text = eq_text.replace("−", "-")
            eq_text = re.sub(r"\|([^|]+)\|", r"Abs(\1)", eq_text)
            # e.g. "4 root(7v+11)" -> "root(4,7v+11)"
            eq_text = re.sub(r"(?i)\b(\d+)\s*root\s*\(\s*([^\)]+?)\s*\)", r"root(\1,\2)", eq_text)
            # root(n,x) -> (x)**(1/(n))
            eq_text = re.sub(r"(?i)\broot\s*\(\s*([^,\)]+)\s*,\s*([^\)]+)\)", r"((\2)**(1/(\1)))", eq_text)
            eq_text = eq_text.replace("^", "**")

            m_eq = re.search(r"(.+?)=(.+)", eq_text)
            if m_eq:
                left = m_eq.group(1)
                right = m_eq.group(2)

                # Drop non-math words that can survive extraction.
                stopwords = (
                    r"(?i)\b(answer|editor|real|number|where|is|a|an|the|and|or|then|write|your|as|"
                    r"single|fraction|solution|solutions|separate|with|commas|click|on|no)\b"
                )
                left = re.sub(stopwords, " ", left)
                right = re.sub(stopwords, " ", right)
                left = re.sub(r"[^A-Za-z0-9_+\-*/^(). ]", " ", left)
                right = re.sub(r"[^A-Za-z0-9_+\-*/^(). ]", " ", right)
                left = re.sub(r"\s+", " ", left).strip()
                right = re.sub(r"\s+", " ", right).strip()
                # Remove stray sentence punctuation from prompt text, e.g.
                # "Solve for v. -7/2 v + 7/2 = ..." -> "-7/2 v + 7/2"
                left = re.sub(r"^[\s\.;:,]+", "", left)
                right = re.sub(r"^[\s\.;:,]+", "", right)
                left = re.sub(r"[\s\.;:,]+$", "", left)
                right = re.sub(r"[\s\.;:,]+$", "", right)

                if left and right:
                    try:
                        sym = sp.Symbol(var_name, real=True)
                        transformations = standard_transformations + (implicit_multiplication_application,)
                        local_dict = {var_name: sym, "Abs": sp.Abs, "sqrt": sp.sqrt}
                        lhs = parse_expr(left, transformations=transformations, local_dict=local_dict, evaluate=True)
                        rhs = parse_expr(right, transformations=transformations, local_dict=local_dict, evaluate=True)
                        sol = sp.solveset(sp.Eq(lhs, rhs), sym, domain=sp.S.Reals)

                        if sol is sp.S.EmptySet:
                            return "no solution"

                        # solveset often returns Intersection(FiniteSet(...), Reals)
                        # for rational equations. Extract finite solutions from
                        # wrappers instead of requiring a bare FiniteSet.
                        finite = None
                        if isinstance(sol, sp.FiniteSet):
                            finite = sol
                        elif isinstance(sol, sp.Intersection):
                            for arg in sol.args:
                                if isinstance(arg, sp.FiniteSet):
                                    finite = arg
                                    break

                        if finite is not None:
                            vals = sorted(list(finite), key=sp.default_sort_key)
                            out_vals = []
                            for v in vals:
                                s = sp.sstr(sp.simplify(v)).replace("**", "^")
                                s = re.sub(r"\s+", "", s)
                                out_vals.append(s)
                            if out_vals:
                                return ",".join(out_vals)
                    except Exception:
                        pass

        return None

    def solve(self, question: str, context: str = "") -> str:
        """
        Solve a single ALEKS question.
        Returns the answer string ready to be typed into ALEKS.

        If `context` is non-empty (e.g. a "previous answer was wrong" hint),
        the cache is bypassed — we always want a fresh attempt.
        """
        # Cache lookup (skipped when there's extra context, e.g. retries)
        key = self._hash(question)
        if not context and key in self.cache:
            self.cache_hits += 1
            log.info(f"  CACHE HIT (saved ~{config.MAX_TOKENS} tokens)")
            return self.cache[key]

        # Deterministic symbolic path should run on both first-pass and
        # retry attempts. This avoids regressing into incorrect LLM algebra
        # after a "Try Again" when the template is symbolically solvable.
        symbolic = self._solve_symbolically(question)
        if symbolic:
            log.info(f"  Symbolic answer: {symbolic}")
            return symbolic

        # Build prompt. Chain-of-thought vastly improves accuracy on
        # algebra — ask the model to show work, then isolate the final
        # answer on the last line prefixed with "ANSWER:".
        prompt = (
            f"{context}\n\n" if context else ""
        ) + (
            f"Question: {question}\n\n"
            "Think step by step. Show the algebra.\n"
            "Then VERIFY your answer by substituting it back into the "
            "original equation and confirming both sides are equal.\n"
            "If the check fails, redo the work.\n"
            "On the FINAL line output exactly:\n"
            "ANSWER: <your final answer in the format described above>"
        )

        # Call API
        self.api_calls += 1
        log.info(f"  Calling model ({self.model})...")

        response = self._chat(
            messages=[
                {"role": "system", "content": config.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=config.MAX_TOKENS,
            temperature=config.TEMPERATURE,
        )

        raw = response.choices[0].message.content.strip()
        tokens = response.usage.prompt_tokens + response.usage.completion_tokens
        self.tokens_used += tokens

        answer = self._extract_answer(raw)

        # If the answer is unusable (e.g. just '.'), force one strict retry.
        if self._is_invalid_answer(answer):
            log.warning(f"  Invalid model answer {answer!r}; requesting strict retry.")
            self.api_calls += 1
            retry = self._chat(
                messages=[
                    {"role": "system", "content": config.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Question: {question}\n"
                            "Return ONLY the final ALEKS answer as plain text. "
                            "No explanation. No label. No punctuation-only output."
                        ),
                    },
                ],
                max_tokens=min(config.MAX_TOKENS, 256),
                temperature=0.0,
            )
            raw2 = retry.choices[0].message.content.strip()
            tokens2 = retry.usage.prompt_tokens + retry.usage.completion_tokens
            self.tokens_used += tokens2
            answer = self._extract_answer(raw2)

        log.info(f"  Answer: {answer} ({tokens} tokens)")

        return answer

    def mark_correct(self, question: str, answer: str):
        """Persist an answer only after ALEKS confirmed it correct."""
        key = self._hash(question)
        clean = (answer or "").strip()
        if not clean:
            return
        self.cache[key] = clean
        self._save_cache()

    def invalidate(self, question: str):
        """Drop the cached answer for ``question`` (e.g. after it turned out wrong)."""
        key = self._hash(question)
        if key in self.cache:
            del self.cache[key]
            self._save_cache()

    def solve_with_steps(self, question: str, context: str = "") -> dict:
        """
        Solve and return both the answer AND step-by-step explanation.
        Used for the console report.
        """
        prompt = question
        if context:
            prompt = f"Topic: {context}\n\nQuestion: {question}"

        response = self._chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a math tutor. First give the FINAL ANSWER on its own line "
                        "prefixed with 'ANSWER: ', then explain the solution step by step."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
            temperature=config.TEMPERATURE,
        )

        raw = response.choices[0].message.content.strip()
        tokens = response.usage.prompt_tokens + response.usage.completion_tokens
        self.tokens_used += tokens

        # Parse answer from explanation
        lines = raw.split("\n")
        answer = ""
        steps = raw
        for line in lines:
            if line.strip().upper().startswith("ANSWER:"):
                answer = line.split(":", 1)[1].strip()
                break

        return {"answer": answer or lines[0], "steps": steps, "tokens": tokens}

    @property
    def stats(self) -> dict:
        return {
            "api_calls": self.api_calls,
            "cache_hits": self.cache_hits,
            "total_tokens": self.tokens_used,
            "cached_answers": len(self.cache),
        }
