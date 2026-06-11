"""Single point of contact with the Gemini API: client construction, key
rotation, and error translation into typed exceptions."""

from __future__ import annotations

import logging
import os
import re

from ..exceptions import ConfigError, LLMError, LLMUnavailable, RateLimited

logger = logging.getLogger("acquisition_analyst")

MODEL_FLASH = "gemini-3.5-flash"
MODEL_PRO = "gemini-3.1-pro"
DEFAULT_MODEL = MODEL_FLASH
SUPPORTED_MODELS = (MODEL_FLASH, MODEL_PRO)


def keys_from_env() -> list[str]:
    """Collect GOOGLE_API_KEY, GOOGLE_API_KEY_2, … in numeric order."""
    def sort_key(var: str) -> int:
        m = re.match(r"GOOGLE_API_KEY_?(\d*)$", var)
        return int(m.group(1)) if m and m.group(1) else 1

    names = [k for k in os.environ if re.match(r"GOOGLE_API_KEY_?\d*$", k)]
    return [os.environ[n].strip() for n in sorted(names, key=sort_key) if os.environ[n].strip()]


class GeminiGateway:
    def __init__(self, api_keys: list[str], model: str = DEFAULT_MODEL):
        if not api_keys:
            raise ConfigError("At least one API key is required.")
        if model not in SUPPORTED_MODELS:
            raise ConfigError(f"Unsupported model '{model}'. Supported: {SUPPORTED_MODELS}")
        self._keys = list(api_keys)
        self.model = model

    def generate(self, contents: str, *, system: str, max_output_tokens: int,
                 model: str | None = None) -> str:
        """Run one generation, rotating across keys on 429/503. Raises typed errors."""
        from google import genai
        from google.genai import types

        last_err: Exception | None = None
        for key in self._keys:
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model=model or self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_output_tokens,
                    ),
                )
                if response.text is None:
                    raise LLMError("Model returned an empty response.")
                return response.text
            except LLMError:
                raise
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                    logger.warning("Gemini key rotation: %s", msg[:120])
                    last_err = e
                    continue
                raise LLMError(msg) from e

        assert last_err is not None
        msg = str(last_err)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            raise RateLimited(f"All {len(self._keys)} API key(s) are rate-limited.") from last_err
        raise LLMUnavailable("Model service unavailable (high demand). Try again shortly.") from last_err
