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

import base64
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
            try:
                text = self.cache_path.read_text().strip()
                self.cache = json.loads(text) if text else {}
                log.info(f"Loaded {len(self.cache)} cached answers")
            except json.JSONDecodeError:
                log.warning("Cache file corrupted — starting fresh")
                self.cache = {}

    def _extract_answer(self, raw: str) -> str:
        """
        Extract just the final answer from the model response.

        qwen2.5-math outputs:
          <think> ... long reasoning ... </think>
          \\boxed{3.14}

        Other models may output:
          "The answer is 3.14"
          "ANSWER: 3.14"
          Multi-line reasoning with answer on last line
        """
        import re
        text = raw.strip()

        # 1. Strip <think>...</think> blocks (qwen2.5-math reasoning)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

        # 2. Extract \boxed{...} — qwen2.5-math wraps its answer in this
        boxed = re.search(r'\\boxed\{([^}]+)\}', text)
        if boxed:
            text = boxed.group(1).strip()

        # 3. Strip LaTeX display/inline math delimiters: \[ ... \], \( ... \), $ ... $
        text = re.sub(r'\\\[.*?\\\]', lambda m: m.group(0)[2:-2].strip(), text, flags=re.DOTALL)
        text = re.sub(r'\\\(.*?\\\)', lambda m: m.group(0)[2:-2].strip(), text, flags=re.DOTALL)
        text = re.sub(r'\$\$.*?\$\$', lambda m: m.group(0)[2:-2].strip(), text, flags=re.DOTALL)
        text = re.sub(r'\$.*?\$', lambda m: m.group(0)[1:-1].strip(), text)

        # 4. Strip remaining LaTeX commands: \approx \cdot \frac{a}{b} etc.
        text = re.sub(r'\\approx\s*', '', text)
        text = re.sub(r'\\cdot\s*', '*', text)
        text = re.sub(r'\\times\s*', '*', text)
        text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'\1/\2', text)
        text = re.sub(r'\\left|\\right|\\,|\\;|\\!', '', text)
        text = re.sub(r'\\[a-zA-Z]+\s*', '', text)  # remove any remaining \commands
        text = text.strip()

        # 3. Remove common answer prefixes
        text = re.sub(
            r'^(?:the\s+answer\s+is|answer\s*[:=]|therefore[,\s]+|so[,\s]+|'
            r'thus[,\s]+|result\s*[:=]|=\s*)',
            '', text, flags=re.IGNORECASE
        ).strip()

        # 4. If multiple lines remain, take the last short non-sentence line
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) > 1:
            for line in reversed(lines):
                if len(line.split()) <= 8 and not line.endswith('.'):
                    text = line
                    break
            else:
                text = lines[-1]

        # 5. Strip trailing punctuation
        text = text.rstrip('.')

        return text

    def _hash(self, question: str) -> str:
        return hashlib.sha256(question.strip().lower().encode()).hexdigest()[:16]

    def bust_cache(self, question: str):
        """Remove a wrong answer from the cache so it won't be reused."""
        key = self._hash(question)
        if key in self.cache:
            del self.cache[key]
            self._save_cache()
            log.info("  Cache entry removed for wrong answer")

    def _save_cache(self):
        self.cache_path.write_text(json.dumps(self.cache, indent=2))

    def _chat(self, messages: list[dict], num_predict: int = None) -> dict:
        """Send a chat request to Ollama's /api/chat endpoint."""
        options = dict(config.OLLAMA_OPTIONS)
        if num_predict:
            options["num_predict"] = num_predict
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": options,
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

        raw = response["message"]["content"].strip()
        answer = self._extract_answer(raw)
        tokens = response.get("eval_count", 0) + response.get("prompt_eval_count", 0)
        self.tokens_used += tokens
        log.info(f"  Answer: {answer} ({tokens} tokens)")

        # Cache it
        self.cache[key] = answer
        self._save_cache()

        return answer

    def image_to_text(self, image_path: Path) -> str:
        """
        Send a screenshot to the vision model and get a precise plain-text
        transcription of the full ALEKS question.
        """
        img_b64 = base64.b64encode(image_path.read_bytes()).decode()

        prompt = (
            "You are reading a math question from the ALEKS online platform.\n\n"
            "TASK: Transcribe the ENTIRE question exactly as it appears. "
            "Do NOT solve it. Do NOT summarize. Copy every single word, number, "
            "symbol, and instruction visible on screen.\n\n"
            "RULES for math notation:\n"
            "- Fractions: write as (numerator)/(denominator), e.g. (3x+1)/(x-2)\n"
            "- Exponents: use ^ symbol, e.g. x^2, e^(2x)\n"
            "- Square roots: sqrt(...), e.g. sqrt(x+1)\n"
            "- Greek letters: spell out, e.g. theta, pi, alpha, beta\n"
            "- Trig functions: sin, cos, tan, sec, csc, cot\n"
            "- Infinity: write as 'inf' or 'infinity'\n"
            "- Absolute value: |x|\n"
            "- Multiplication: use * or 'times'\n"
            "- Answer input box: mark as [INPUT BOX]\n"
            "- Multiple choice options: list each on its own line as A) B) C) D)\n\n"
            "OUTPUT FORMAT:\n"
            "Question: <full question text>\n"
            "Instructions: <any instructions shown, e.g. 'round to nearest hundredth'>\n"
            "Choices (if any): <list options>\n"
        )

        payload = {
            "model": config.OLLAMA_VISION_MODEL,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 1024},
        }

        resp = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        log.info(f"  Vision extracted ({len(text)} chars): {text[:120].replace(chr(10),' ')}")
        return text

    def solve_from_screenshot(self, image_path: Path, dom_text: str = "",
                               context: str = "",
                               wrong_answers: list[str] | None = None) -> str:
        """
        Solve using DOM text as primary source.
        Vision model is used ONLY to fill in math formulas the DOM missed.
        """
        vision_text = self.image_to_text(image_path)

        # Merge: prefer DOM text for words/instructions, vision for math symbols
        if dom_text and vision_text:
            # Use DOM text as base — it has the cleanest structure
            # Append vision output only if it adds new math content
            question_text = (
                f"{dom_text}\n\n"
                f"[Visual math from screenshot]:\n{vision_text}"
            )
        elif dom_text:
            question_text = dom_text
        else:
            question_text = vision_text or "Unknown question"

        if wrong_answers:
            retry_context = (
                f"{context}\n\n"
                f"FULL QUESTION:\n{question_text}\n\n"
                f"Previously WRONG answers — do NOT repeat these: {', '.join(wrong_answers)}\n"
                f"Think carefully and give a DIFFERENT correct answer."
            )
            cache_key = question_text + f"__retry{len(wrong_answers)}"
            return self.solve(cache_key, context=retry_context)

        return self.solve(question_text, context=context)

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
