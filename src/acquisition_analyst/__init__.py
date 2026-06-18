"""acquisition_analyst — buy-side M&A due diligence SDK.

Deterministic SaaS-metric scoring against cohort benchmarks, plus
LLM-written IC memos and due-diligence question generation.

    from acquisition_analyst import Analyst, AnalysisRequest

    analyst = Analyst()  # reads GOOGLE_API_KEY from the environment
    findings = analyst.analyze(AnalysisRequest(**payload))
"""

from .client import Analyst, EngagementContext
from .exceptions import AnalystError, ConfigError, LLMError, LLMUnavailable, RateLimited
from .llm import (
    DEFAULT_MODEL, MODEL_FLASH, MODEL_PRO, SUPPORTED_MODELS,
    GEMINI_FLASH, GEMINI_PRO,
    CLAUDE_SONNET, CLAUDE_HAIKU, CLAUDE_OPUS,
    GPT_4O, GPT_4O_MINI,
    GeminiGateway, AnthropicGateway, OpenAIGateway, LLMGateway,
    template_memo,
)
from .models import (
    AnalysisRequest,
    DDQuestion,
    Findings,
    GradedMetric,
    MetricSeries,
    Scorecard,
)
from .scoring import BenchmarkSet

__version__ = "0.1.0"

__all__ = [
    "Analyst",
    "EngagementContext",
    "LLMGateway",
    "GeminiGateway",
    "AnthropicGateway",
    "OpenAIGateway",
    "GEMINI_FLASH", "GEMINI_PRO",
    "CLAUDE_SONNET", "CLAUDE_HAIKU", "CLAUDE_OPUS",
    "GPT_4O", "GPT_4O_MINI",
    "AnalysisRequest",
    "MetricSeries",
    "Findings",
    "GradedMetric",
    "Scorecard",
    "DDQuestion",
    "BenchmarkSet",
    "template_memo",
    "DEFAULT_MODEL",
    "MODEL_FLASH",
    "MODEL_PRO",
    "SUPPORTED_MODELS",
    "AnalystError",
    "ConfigError",
    "LLMError",
    "RateLimited",
    "LLMUnavailable",
    "__version__",
]
