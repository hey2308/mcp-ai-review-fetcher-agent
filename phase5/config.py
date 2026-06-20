"""Configuration loading and startup validation for Phase 5."""

import os
from pathlib import Path

import yaml

# Env vars override config.yaml when set (local .env or CI/Render secrets)
ENV_OVERRIDES = {
    "MCP_SERVER_URL": "mcp_server_url",
    "EMAIL_ALIAS": "email_alias",
    "GOOGLE_DOC_ID": "google_doc_id",
}

REQUIRED_CONFIG_KEYS = [
    "review_window_weeks",
    "app_store_id",
    "play_store_package",
    "max_themes",
    "pulse_themes_displayed",
    "max_words",
    "llm_provider",
    "llm_model",
    "max_reviews_to_process",
    "llm_batch_size",
    "llm_text_max_words",
    "llm_max_rpm",
    "llm_max_tpm",
    "llm_max_tokens_per_run",
    "email_alias",
    "mcp_server_url",
    "google_doc_id",
]


class ConfigError(Exception):
    """Raised when config.yaml is missing or invalid."""


def load_config(config_path: str = "config.yaml") -> dict:
    if not os.path.exists(config_path):
        raise ConfigError(f"Configuration file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return apply_env_overrides(config)


def apply_env_overrides(config: dict) -> dict:
    """Merge environment variables into config (env wins over config.yaml)."""
    merged = dict(config)
    for env_key, config_key in ENV_OVERRIDES.items():
        value = os.environ.get(env_key)
        if value and str(value).strip():
            merged[config_key] = str(value).strip()
    return merged


PUBLISH_CONFIG_KEYS = ("google_doc_id", "email_alias", "mcp_server_url")


def validate_config(config: dict, *, offline: bool = False, skip_publish: bool = False) -> None:
    """Validate config before any tools run."""
    skip_publish_check = offline or skip_publish
    required_keys = [
        k
        for k in REQUIRED_CONFIG_KEYS
        if not (skip_publish_check and k in PUBLISH_CONFIG_KEYS)
    ]
    missing = [key for key in required_keys if not config.get(key)]
    if missing:
        raise ConfigError(f"Missing required config keys: {', '.join(missing)}")

    if config.get("llm_provider") != "groq":
        raise ConfigError(f"Unsupported llm_provider: {config.get('llm_provider')}")

    if not offline and not os.environ.get("GROQ_API_KEY"):
        env_path = Path(".env")
        hint = "Set GROQ_API_KEY in .env or environment."
        if not env_path.exists():
            hint += " Copy .env.example to .env and add your key."
        raise ConfigError(f"GROQ_API_KEY is required for live runs. {hint}")

    if offline or skip_publish:
        return

    if not str(config.get("google_doc_id", "")).strip():
        raise ConfigError("google_doc_id must be set in config.yaml or GOOGLE_DOC_ID env")

    if not str(config.get("email_alias", "")).strip():
        raise ConfigError("email_alias must be set in config.yaml or EMAIL_ALIAS env")

    if not str(config.get("mcp_server_url", "")).strip():
        raise ConfigError("mcp_server_url must be set in config.yaml or MCP_SERVER_URL env")
