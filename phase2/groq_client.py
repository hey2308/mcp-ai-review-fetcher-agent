"""Throttled Groq API client for Phase 2."""

import json
import logging
import os
import re
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


class GroqBudgetExceeded(Exception):
    """Raised when estimated or actual token budget would be exceeded."""


class GroqClient:
    """Groq chat completions with RPM/TPM throttling and token tracking."""

    def __init__(
        self,
        model: str,
        max_rpm: int = 24,
        max_tpm: int = 10000,
        max_tokens_per_run: int = 90000,
        min_request_interval: float = 2.5,
    ):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is required. Add it to .env in the project root "
                "(see .env.example) or set the environment variable."
            )
        from groq import Groq

        self.client = Groq(api_key=api_key)
        self.model = model
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self.max_tokens_per_run = max_tokens_per_run
        self.min_request_interval = min_request_interval

        self._request_times: deque[float] = deque()
        self._token_window: deque[tuple[float, int]] = deque()
        self._last_request_at: float = 0.0
        self.total_requests = 0
        self.total_tokens = 0

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate (~4 chars per token)."""
        return max(1, len(text) // 4)

    def preflight_check(self, estimated_tokens: int) -> None:
        if estimated_tokens > self.max_tokens_per_run:
            raise GroqBudgetExceeded(
                f"Pre-flight estimate {estimated_tokens} exceeds run budget "
                f"{self.max_tokens_per_run}"
            )

    def _prune_windows(self, now: float) -> None:
        while self._request_times and now - self._request_times[0] > 60:
            self._request_times.popleft()
        while self._token_window and now - self._token_window[0][0] > 60:
            self._token_window.popleft()

    def _rolling_tpm(self) -> int:
        return sum(tokens for _, tokens in self._token_window)

    def _throttle(self, estimated_tokens: int) -> None:
        now = time.time()
        self._prune_windows(now)

        if self.total_tokens + estimated_tokens > self.max_tokens_per_run:
            raise GroqBudgetExceeded(
                f"Run token budget exceeded: {self.total_tokens + estimated_tokens} "
                f"> {self.max_tokens_per_run}"
            )

        while self._rolling_tpm() + estimated_tokens > self.max_tpm:
            logger.info("TPM limit approached; pausing 5s...")
            time.sleep(5)
            now = time.time()
            self._prune_windows(now)

        while len(self._request_times) >= self.max_rpm:
            sleep_for = 60 - (now - self._request_times[0]) + 0.1
            if sleep_for > 0:
                logger.info("RPM limit approached; pausing %.1fs...", sleep_for)
                time.sleep(sleep_for)
            now = time.time()
            self._prune_windows(now)

        elapsed = now - self._last_request_at
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        retries: int = 1,
    ) -> Any:
        """Call Groq and parse JSON from the response."""
        estimated = self.estimate_tokens(system_prompt + user_prompt) + 500
        self._throttle(estimated)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                now = time.time()
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                self._last_request_at = time.time()
                self._request_times.append(self._last_request_at)
                self.total_requests += 1

                content = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                if usage:
                    tokens_used = (usage.prompt_tokens or 0) + (
                        usage.completion_tokens or 0
                    )
                else:
                    tokens_used = self.estimate_tokens(content) + estimated
                self.total_tokens += tokens_used
                self._token_window.append((self._last_request_at, tokens_used))

                return _parse_json(content)
            except Exception as err:
                last_error = err
                logger.warning(
                    "Groq call failed (attempt %d/%d): %s",
                    attempt + 1,
                    retries + 1,
                    err,
                )
                if attempt < retries:
                    time.sleep(2)

        raise RuntimeError(f"Groq call failed after retries: {last_error}")


def _parse_json(content: str) -> Any:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            return json.loads(match.group())
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            return json.loads(match.group())
        raise
