"""Cost estimates for external model calls; rates are operator-configured."""

from decimal import Decimal

from personal_ai_life_os.config import Settings

MILLION = Decimal(1000000)


def model_cost_usd(input_tokens: int, output_tokens: int, config: Settings) -> Decimal | None:
    """Return the configured estimate, or None when current provider rates are absent."""
    input_rate = config.model_input_cost_per_million_usd
    output_rate = config.model_output_cost_per_million_usd
    if input_rate <= 0 or output_rate <= 0:
        return None
    return (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / MILLION


def model_rates_configured(config: Settings) -> bool:
    return config.model_input_cost_per_million_usd > 0 and config.model_output_cost_per_million_usd > 0
