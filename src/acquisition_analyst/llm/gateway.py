"""LLM provider adapters. `LLMGateway` is the interface; built-in implementations
cover Gemini, Anthropic, and OpenAI. Pass any object implementing `LLMGateway`
to `Analyst(gateway=...)` to use a custom provider.

Provider is auto-detected from the model name:
  claude-*   → AnthropicGateway  (reads ANTHROPIC_API_KEY)
  gpt-* / o* → OpenAIGateway     (reads OPENAI_API_KEY)
  gemini-*   → GeminiGateway     (reads GOOGLE_API_KEY[_N])

Install the matching extra:
  pip install 'acquisition-analyst[anthropic]'
  pip install 'acquisition-analyst[openai]'
  pip install 'acquisition-analyst[gemini]'
"""

from __future__ import annotations

import logging
import os
import re
from typing import Protocol, runtime_checkable

from ..exceptions import ConfigError, LLMError, LLMUnavailable, RateLimited

logger = logging.getLogger("acquisition_analyst")

# ── Model constants ───────────────────────────────────────────────────────────

GEMINI_FLASH = "gemini-3.5-flash"
GEMINI_PRO   = "gemini-3.1-pro"

CLAUDE_SONNET = "claude-sonnet-4-6"
CLAUDE_HAIKU  = "claude-haiku-4-5-20251001"
CLAUDE_OPUS   = "claude-opus-4-8"

GPT_4O      = "gpt-4o"
GPT_4O_MINI = "gpt-4o-mini"

# Backward-compat aliases
MODEL_FLASH = GEMINI_FLASH
MODEL_PRO   = GEMINI_PRO
DEFAULT_MODEL = GEMINI_FLASH

SUPPORTED_MODELS = (
    GEMINI_FLASH, GEMINI_PRO,
    CLAUDE_SONNET, CLAUDE_HAIKU, CLAUDE_OPUS,
    GPT_4O, GPT_4O_MINI,
)

_GEMINI_MODELS    = {GEMINI_FLASH, GEMINI_PRO}
_ANTHROPIC_MODELS = {CLAUDE_SONNET, CLAUDE_HAIKU, CLAUDE_OPUS}
_OPENAI_MODELS    = {GPT_4O, GPT_4O_MINI}


# ── Protocol ─────────────────────────────────────────────────────────────────

@runtime_checkable
class LLMGateway(Protocol):
    """Adapter interface for an LLM provider.

    Implementations raise the SDK's typed exceptions (LLMError, RateLimited,
    LLMUnavailable) so callers handle failures uniformly regardless of provider.
    """

    model: str

    def generate(self, contents: str, *, system: str, max_output_tokens: int,
                 model: str | None = None) -> str: ...


# ── Gemini ────────────────────────────────────────────────────────────────────

def keys_from_env() -> list[str]:
    """Collect GOOGLE_API_KEY, GOOGLE_API_KEY_2, … in numeric order."""
    def sort_key(var: str) -> int:
        m = re.match(r"GOOGLE_API_KEY_?(\d*)$", var)
        return int(m.group(1)) if m and m.group(1) else 1

    names = [k for k in os.environ if re.match(r"GOOGLE_API_KEY_?\d*$", k)]
    return [os.environ[n].strip() for n in sorted(names, key=sort_key) if os.environ[n].strip()]


class GeminiGateway:
    def __init__(self, api_keys: list[str], model: str = GEMINI_FLASH):
        if not api_keys:
            raise ConfigError("At least one API key is required.")
        if model not in _GEMINI_MODELS:
            raise ConfigError(f"Unsupported Gemini model '{model}'. Supported: {sorted(_GEMINI_MODELS)}")
        self._keys = list(api_keys)
        self.model = model

    def generate(self, contents: str, *, system: str, max_output_tokens: int,
                 model: str | None = None) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ConfigError("Install Gemini: pip install 'acquisition-analyst[gemini]'")

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


# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicGateway:
    def __init__(self, api_key: str, model: str = CLAUDE_SONNET):
        if not api_key:
            raise ConfigError("ANTHROPIC_API_KEY is required.")
        if model not in _ANTHROPIC_MODELS:
            raise ConfigError(f"Unsupported Anthropic model '{model}'. Supported: {sorted(_ANTHROPIC_MODELS)}")
        self._key = api_key
        self.model = model

    def generate(self, contents: str, *, system: str, max_output_tokens: int,
                 model: str | None = None) -> str:
        try:
            import anthropic
        except ImportError:
            raise ConfigError("Install Anthropic: pip install 'acquisition-analyst[anthropic]'")

        client = anthropic.Anthropic(api_key=self._key)
        try:
            message = client.messages.create(
                model=model or self.model,
                max_tokens=max_output_tokens,
                system=system,
                messages=[{"role": "user", "content": contents}],
            )
            return message.content[0].text
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower():
                raise RateLimited(msg) from e
            if "529" in msg or "overloaded" in msg.lower():
                raise LLMUnavailable(msg) from e
            raise LLMError(msg) from e


# ── OpenAI ────────────────────────────────────────────────────────────────────

class OpenAIGateway:
    def __init__(self, api_key: str, model: str = GPT_4O):
        if not api_key:
            raise ConfigError("OPENAI_API_KEY is required.")
        if model not in _OPENAI_MODELS:
            raise ConfigError(f"Unsupported OpenAI model '{model}'. Supported: {sorted(_OPENAI_MODELS)}")
        self._key = api_key
        self.model = model

    def generate(self, contents: str, *, system: str, max_output_tokens: int,
                 model: str | None = None) -> str:
        try:
            import openai
        except ImportError:
            raise ConfigError("Install OpenAI: pip install 'acquisition-analyst[openai]'")

        client = openai.OpenAI(api_key=self._key)
        try:
            response = client.chat.completions.create(
                model=model or self.model,
                max_tokens=max_output_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": contents},
                ],
            )
            return response.choices[0].message.content
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower():
                raise RateLimited(msg) from e
            if "503" in msg or "unavailable" in msg.lower():
                raise LLMUnavailable(msg) from e
            raise LLMError(msg) from e


# ── Factory ───────────────────────────────────────────────────────────────────

def _gateway_for(model: str, api_keys: list[str] | None) -> LLMGateway | None:
    """Build the right gateway from a model name, reading env vars as fallback."""
    if model in _ANTHROPIC_MODELS:
        key = (api_keys[0] if api_keys else None) or os.environ.get("ANTHROPIC_API_KEY", "").strip() or None
        return AnthropicGateway(key, model) if key else None
    elif model in _OPENAI_MODELS:
        key = (api_keys[0] if api_keys else None) or os.environ.get("OPENAI_API_KEY", "").strip() or None
        return OpenAIGateway(key, model) if key else None
    else:
        keys = api_keys or keys_from_env() or None
        return GeminiGateway(keys, model) if keys else None
