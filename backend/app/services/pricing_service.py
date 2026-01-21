"""Service for model pricing and cost calculation.

Pricing logic adapted from ccusage by ryoppippi
https://github.com/ryoppippi/ccusage
Licensed under MIT
"""
from typing import Optional


class PricingService:
    """Service for model pricing and cost calculation."""

    # Default token threshold for tiered pricing (200k tokens)
    TIERED_THRESHOLD = 200_000

    # Model pricing data (costs per token)
    # Based on LiteLLM pricing data
    MODEL_PRICING = {
        # Claude Sonnet 4 (May 2025)
        "claude-sonnet-4-20250514": {
            "input": 3.00 / 1_000_000,
            "output": 15.00 / 1_000_000,
            "cache_creation": 3.75 / 1_000_000,
            "cache_read": 0.30 / 1_000_000,
            "input_above_200k": 6.00 / 1_000_000,
            "output_above_200k": 22.50 / 1_000_000,
            "cache_creation_above_200k": 7.50 / 1_000_000,
            "cache_read_above_200k": 0.60 / 1_000_000,
        },
        # Claude Opus 4 (May 2025)
        "claude-opus-4-20250514": {
            "input": 15.00 / 1_000_000,
            "output": 75.00 / 1_000_000,
            "cache_creation": 18.75 / 1_000_000,
            "cache_read": 1.50 / 1_000_000,
            "input_above_200k": 30.00 / 1_000_000,
            "output_above_200k": 112.50 / 1_000_000,
            "cache_creation_above_200k": 37.50 / 1_000_000,
            "cache_read_above_200k": 3.00 / 1_000_000,
        },
        # Claude Opus 4.5 (November 2025)
        "claude-opus-4-5-20251101": {
            "input": 15.00 / 1_000_000,
            "output": 75.00 / 1_000_000,
            "cache_creation": 18.75 / 1_000_000,
            "cache_read": 1.50 / 1_000_000,
            "input_above_200k": 30.00 / 1_000_000,
            "output_above_200k": 112.50 / 1_000_000,
            "cache_creation_above_200k": 37.50 / 1_000_000,
            "cache_read_above_200k": 3.00 / 1_000_000,
        },
        # Claude 3.5 Sonnet (October 2024)
        "claude-3-5-sonnet-20241022": {
            "input": 3.00 / 1_000_000,
            "output": 15.00 / 1_000_000,
            "cache_creation": 3.75 / 1_000_000,
            "cache_read": 0.30 / 1_000_000,
        },
        # Claude 3.5 Sonnet (June 2024)
        "claude-3-5-sonnet-20240620": {
            "input": 3.00 / 1_000_000,
            "output": 15.00 / 1_000_000,
            "cache_creation": 3.75 / 1_000_000,
            "cache_read": 0.30 / 1_000_000,
        },
        # Claude 3.5 Haiku (October 2024)
        "claude-3-5-haiku-20241022": {
            "input": 0.80 / 1_000_000,
            "output": 4.00 / 1_000_000,
            "cache_creation": 1.00 / 1_000_000,
            "cache_read": 0.08 / 1_000_000,
        },
        # Claude 3 Opus (February 2024)
        "claude-3-opus-20240229": {
            "input": 15.00 / 1_000_000,
            "output": 75.00 / 1_000_000,
            "cache_creation": 18.75 / 1_000_000,
            "cache_read": 1.50 / 1_000_000,
        },
        # Claude 3 Sonnet (February 2024)
        "claude-3-sonnet-20240229": {
            "input": 3.00 / 1_000_000,
            "output": 15.00 / 1_000_000,
            "cache_creation": 3.75 / 1_000_000,
            "cache_read": 0.30 / 1_000_000,
        },
        # Claude 3 Haiku (March 2024)
        "claude-3-haiku-20240307": {
            "input": 0.25 / 1_000_000,
            "output": 1.25 / 1_000_000,
            "cache_creation": 0.30 / 1_000_000,
            "cache_read": 0.03 / 1_000_000,
        },
    }

    # Provider prefixes for model name matching
    PROVIDER_PREFIXES = [
        "anthropic/",
        "claude-",
        "claude-3-",
        "claude-3-5-",
    ]

    def normalize_model_name(self, model_name: str) -> str:
        """Normalize model name by removing provider prefixes."""
        normalized = model_name.lower()
        for prefix in self.PROVIDER_PREFIXES:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
        return normalized

    def get_model_pricing(self, model_name: str) -> Optional[dict]:
        """Get pricing data for a model.

        Args:
            model_name: Model name (e.g., "claude-sonnet-4-20250514")

        Returns:
            Pricing dict or None if model not found
        """
        # Try direct match first
        if model_name in self.MODEL_PRICING:
            return self.MODEL_PRICING[model_name]

        # Try with provider prefixes
        for prefix in self.PROVIDER_PREFIXES:
            full_name = f"{prefix}{model_name}"
            if full_name in self.MODEL_PRICING:
                return self.MODEL_PRICING[full_name]

        # Try normalized matching
        normalized = self.normalize_model_name(model_name)
        for key in self.MODEL_PRICING:
            if self.normalize_model_name(key) == normalized:
                return self.MODEL_PRICING[key]

        # Fuzzy match - check if model name contains a known model
        for key in self.MODEL_PRICING:
            if key in model_name or model_name in key:
                return self.MODEL_PRICING[key]

        return None

    def calculate_tiered_cost(
        self,
        total_tokens: int,
        base_price: Optional[float],
        tiered_price: Optional[float],
        threshold: int = TIERED_THRESHOLD,
    ) -> float:
        """Calculate cost with tiered pricing.

        For models with 1M context window, tokens above threshold are charged
        at a higher rate.

        Args:
            total_tokens: Total number of tokens
            base_price: Price per token for tokens up to threshold
            tiered_price: Price per token for tokens above threshold
            threshold: Token threshold for tiered pricing

        Returns:
            Total cost in USD
        """
        if total_tokens <= 0:
            return 0.0

        if total_tokens > threshold and tiered_price is not None:
            tokens_below = min(total_tokens, threshold)
            tokens_above = max(0, total_tokens - threshold)

            tiered_cost = tokens_above * tiered_price
            if base_price is not None:
                tiered_cost += tokens_below * base_price
            return tiered_cost

        if base_price is not None:
            return total_tokens * base_price

        return 0.0

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        model: Optional[str] = None,
    ) -> float:
        """Calculate total cost for token usage.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cache_creation_tokens: Number of cache creation tokens
            cache_read_tokens: Number of cache read tokens
            model: Model name for pricing lookup

        Returns:
            Total cost in USD
        """
        if model is None:
            return 0.0

        pricing = self.get_model_pricing(model)
        if pricing is None:
            return 0.0

        # Calculate input cost (with tiered pricing if available)
        input_cost = self.calculate_tiered_cost(
            input_tokens,
            pricing.get("input"),
            pricing.get("input_above_200k"),
        )

        # Calculate output cost (with tiered pricing if available)
        output_cost = self.calculate_tiered_cost(
            output_tokens,
            pricing.get("output"),
            pricing.get("output_above_200k"),
        )

        # Calculate cache creation cost (with tiered pricing if available)
        cache_creation_cost = self.calculate_tiered_cost(
            cache_creation_tokens,
            pricing.get("cache_creation"),
            pricing.get("cache_creation_above_200k"),
        )

        # Calculate cache read cost (with tiered pricing if available)
        cache_read_cost = self.calculate_tiered_cost(
            cache_read_tokens,
            pricing.get("cache_read"),
            pricing.get("cache_read_above_200k"),
        )

        return input_cost + output_cost + cache_creation_cost + cache_read_cost

    def get_supported_models(self) -> list[str]:
        """Get list of supported model names."""
        return list(self.MODEL_PRICING.keys())
