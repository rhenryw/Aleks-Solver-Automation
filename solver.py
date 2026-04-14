"""
solver.py — Ollama (local AI) solver with answer caching.

Uses Ollama's REST API to run a local LLM for solving ALEKS questions.
Same architecture as the original Claude solver:
  1. Questions are extracted as TEXT from the browser (0 tokens for reading)
  2. SHA-256 cache prevents duplicate API calls
  3. Minimal prompt: system instruction + question only
  4. Low num_predict since answers are short

Requirements:
  - Ollama must be running: `ollama serve`
  - A model must be pulled: `ollama pull qwen2.5:7b`
"""

import hashlib
import json
import logging
from pathlib import Path

import requests

import config

log = logging.getLogger("solver")


class Solver:
    def __init__(self):
        self.base_url = config.OLLAMA_BASE_URL
        self.model = config.OLLAMA_MODEL
        self.tokens_used = 0
        self.cache_hits = 0
        self.api_calls = 0

        # Verify Ollama is running
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            log.info(f"Ollama connected — {len(models)} models available")

            # Check if the configured model is pulled
            # Model names can be "qwen2.5:7b" or "qwen2.5:7b-instruct" etc.
            model_base = self.model.split(":")[0]
            found = any(model_base in m for m in models)
            if not found:
                log.warning(
                    f"Model '{self.model}' not found. Available: {models}\n"
                    f"  Pull it with: ollama pull {self.model}"
                )
        except requests.ConnectionError:
            raise EnvironmentError(
                "Cannot connect to Ollama. Make sure it's running:\n"
                "  1. Install: https://ollama.com/download\n"
                "  2. Start:   ollama serve\n"
                f"  3. Pull model: ollama pull {self.model}"
            )

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

    def _chat(self, messages: list[dict], num_predict: int = None) -> dict:
        """
        Send a chat request to Ollama's /api/chat endpoint.
        Returns the full response dict.
        
        This mirrors the Anthropic client.messages.create() pattern.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": config.OLLAMA_TEMPERATURE,
                "num_predict": num_predict or config.OLLAMA_NUM_PREDICT,
            },
        }

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=120,  # Local models can be slow on first request
        )
        resp.raise_for_status()
        return resp.json()

    def solve(self, question: str, context: str = "") -> str:
        """
        Solve a single ALEKS question.
        Returns the answer string ready to be typed into ALEKS.
        """
        # Check cache first (0 tokens)
        key = self._hash(question)
        if key in self.cache:
            self.cache_hits += 1
            log.info(f"  CACHE HIT (saved a model call)")
            return self.cache[key]

        # Build prompt
        prompt = question
        if context:
            prompt = f"Topic: {context}\n\nQuestion: {question}"

        # Call Ollama
        self.api_calls += 1
        log.info(f"  Calling Ollama ({self.model})...")

        messages = [
            {"role": "system", "content": config.SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        response = self._chat(messages)

        answer = response["message"]["content"].strip()
        tokens = response.get("eval_count", 0) + response.get("prompt_eval_count", 0)
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

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a math tutor. First give the FINAL ANSWER on its own line "
                    "prefixed with 'ANSWER: ', then explain the solution step by step."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        response = self._chat(messages, num_predict=2048)

        raw = response["message"]["content"].strip()
        tokens = response.get("eval_count", 0) + response.get("prompt_eval_count", 0)
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
