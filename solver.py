"""
solver.py — Claude API solver with answer caching.

Token efficiency:
  1. Questions are extracted as TEXT from the browser (0 tokens for reading)
  2. SHA-256 cache prevents duplicate API calls
  3. Minimal prompt: system instruction + question only
  4. Low max_tokens since answers are short
"""

import hashlib
import json
import os
import logging
from pathlib import Path

from anthropic import Anthropic

import config

log = logging.getLogger("solver")


class Solver:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "Missing ANTHROPIC_API_KEY. Run:\n"
                '  set ANTHROPIC_API_KEY=your-key-here   (CMD)\n'
                '  $env:ANTHROPIC_API_KEY="your-key-here" (PowerShell)'
            )
        self.client = Anthropic(api_key=api_key)
        self.tokens_used = 0
        self.cache_hits = 0
        self.api_calls = 0

        # Load cache
        self.cache_path = Path("answer_cache.json")
        self.cache: dict[str, str] = {}
        if self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text())
            log.info(f"Loaded {len(self.cache)} cached answers")

    def _hash(self, question: str) -> str:
        return hashlib.sha256(question.strip().lower().encode()).hexdigest()[:16]

    def _save_cache(self):
        self.cache_path.write_text(json.dumps(self.cache, indent=2))

    def solve(self, question: str, context: str = "") -> str:
        """
        Solve a single ALEKS question.
        Returns the answer string ready to be typed into ALEKS.
        """
        # Check cache first (0 tokens)
        key = self._hash(question)
        if key in self.cache:
            self.cache_hits += 1
            log.info(f"  CACHE HIT (saved ~{config.CLAUDE_MAX_TOKENS} tokens)")
            return self.cache[key]

        # Build prompt
        prompt = question
        if context:
            prompt = f"Topic: {context}\n\nQuestion: {question}"

        # Call Claude
        self.api_calls += 1
        log.info(f"  Calling Claude ({config.CLAUDE_MODEL})...")

        response = self.client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=config.CLAUDE_MAX_TOKENS,
            temperature=config.CLAUDE_TEMPERATURE,
            system=config.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        answer = response.content[0].text.strip()
        tokens = response.usage.input_tokens + response.usage.output_tokens
        self.tokens_used += tokens
        log.info(f"  Answer: {answer} ({tokens} tokens)")

        # Cache it
        self.cache[key] = answer
        self._save_cache()

        return answer

    def solve_with_steps(self, question: str, context: str = "") -> dict:
        """
        Solve and return both the answer AND step-by-step explanation.
        Used for the console report.
        """
        prompt = question
        if context:
            prompt = f"Topic: {context}\n\nQuestion: {question}"

        response = self.client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2048,
            temperature=config.CLAUDE_TEMPERATURE,
            system=(
                "You are a math tutor. First give the FINAL ANSWER on its own line "
                "prefixed with 'ANSWER: ', then explain the solution step by step."
            ),
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        tokens = response.usage.input_tokens + response.usage.output_tokens
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
