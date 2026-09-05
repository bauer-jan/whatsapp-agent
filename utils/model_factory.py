"""Build a Strands provider without falling back to an unintended backend."""

import os

from utils.config import ModelConfig


KEY_VARIABLES = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def validate_model_credentials(config: ModelConfig) -> None:
    """Fail before connecting to WhatsApp when a direct API key is missing."""
    variable = KEY_VARIABLES.get(config.provider)
    if variable and not os.environ.get(variable, "").strip():
        raise ValueError(f"Set {variable} in your environment or local .env file")


def create_model(config: ModelConfig):
    """Create a fresh provider per agent, including bootstrap and heartbeats."""
    validate_model_credentials(config)
    if config.provider == "bedrock":
        from strands.models import BedrockModel

        kwargs = {"max_tokens": config.max_tokens}
        if config.model_id:
            kwargs["model_id"] = config.model_id
        return BedrockModel(**kwargs)

    client_args = {
        "api_key": os.environ[KEY_VARIABLES[config.provider]],
        "timeout": 30.0,
        "max_retries": 1,
    }
    if config.base_url:
        client_args["base_url"] = config.base_url
    if config.provider == "openai":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            model_id=config.model_id,
            client_args=client_args,
            params={"max_completion_tokens": config.max_tokens},
        )

    from strands.models.anthropic import AnthropicModel

    return AnthropicModel(
        model_id=config.model_id,
        max_tokens=config.max_tokens,
        client_args=client_args,
    )
