"""Typed exception hierarchy. SDK code raises these — it never silently degrades."""


class AnalystError(Exception):
    """Base class for all acquisition_analyst errors."""


class ConfigError(AnalystError):
    """Missing or invalid configuration (e.g. no API keys when an LLM call is required)."""


class LLMError(AnalystError):
    """An LLM call failed."""


class RateLimited(LLMError):
    """All configured API keys are rate-limited (HTTP 429)."""


class LLMUnavailable(LLMError):
    """The model service is overloaded or down (HTTP 503)."""
