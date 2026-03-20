"""
Model router — selects appropriate model based on task complexity.

Routing logic:
  - "small"  → fast/cheap model (8B, e.g. qwen2.5:8b, llama3.1:8b)
  - "medium" → balanced model (14B, default)
  - "large"  → powerful model (30B+, e.g. qwen2.5:32b, deepseek-r1)
  - "code"   → code-specialized model
  - explicit model_hint overrides routing

Complexity scoring heuristics:
  - Multi-step prompts → large
  - Implementation/code prompts → code or large
  - Review/analysis prompts → medium
  - Planning prompts → medium
  - Simple Q&A → small
"""

from __future__ import annotations

import re
from typing import Optional

from nebulus_atom.utils.logger import setup_logger

logger = setup_logger(__name__)


# Model tiers — resolved against available models at runtime
MODEL_TIERS = {
    "small": ["qwen2.5:8b", "llama3.1:8b", "mistral:7b"],
    "medium": ["qwen2.5:14b", "llama3.1:14b", "mistral:12b"],
    "large": ["qwen2.5:32b", "deepseek-r1:32b", "llama3.1:70b"],
    "code": ["qwen2.5-coder:14b", "deepseek-coder:6.7b", "codellama:13b"],
}

# Keywords that suggest complexity tier
COMPLEXITY_SIGNALS = {
    "large": [
        r"\bimplement\b",
        r"\bwrite.*code\b",
        r"\bbuild\b",
        r"\bcreate.*function\b",
        r"\brefactor\b",
        r"\bmulti.?step\b",
        r"\barchitect\b",
        r"\bdesign\b",
        r"\bcomplex\b",
        r"\badvanced\b",
    ],
    "code": [
        r"\btest\b",
        r"\bpytest\b",
        r"\bunit test\b",
        r"\bfix.*bug\b",
        r"\bdebug\b",
        r"\bcode review\b",
    ],
    "small": [
        r"\bsummariz\b",
        r"\blist\b",
        r"\bwhat is\b",
        r"\bexplain\b",
        r"\bformat\b",
        r"\bconvert\b",
    ],
}


class ModelRouter:
    """Routes workflow steps to appropriate models based on complexity."""

    def __init__(self, default_model: Optional[str] = None):
        self.default_model = default_model or "qwen2.5:14b"

    def route(self, prompt: str, model_hint: Optional[str] = None) -> str:
        """
        Select model for a given prompt.

        Args:
            prompt: The rendered prompt text
            model_hint: Explicit hint from workflow definition

        Returns:
            Model name string
        """
        # Explicit hint always wins
        if model_hint:
            # If hint is a tier name, expand it
            if model_hint in MODEL_TIERS:
                model = MODEL_TIERS[model_hint][0]
                logger.debug(f"Model router: hint={model_hint} → {model}")
                return model
            # Otherwise treat as explicit model name
            logger.debug(f"Model router: explicit model={model_hint}")
            return model_hint

        # Score complexity
        tier = self._score_complexity(prompt)
        model = MODEL_TIERS[tier][0]
        logger.debug(f"Model router: scored tier={tier} → {model}")
        return model

    def _score_complexity(self, prompt: str) -> str:
        """Heuristic scoring — returns tier name."""
        text = prompt.lower()

        # Check each tier, large first (most specific)
        for tier in ("large", "code", "small"):
            for pattern in COMPLEXITY_SIGNALS[tier]:
                if re.search(pattern, text):
                    return tier

        return "medium"
