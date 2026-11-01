"""Application configuration loaded from environment variables and .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_OPENROUTER_MODEL = "google/gemma-4-31b-it:free"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_REFERENCE_DATE = "2026-03-23"
DEFAULT_DATA_DIR = "data"
PLACEHOLDER_KEY = "your_openrouter_api_key_here"


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings for the Empório da Música agent."""

    openrouter_api_key: str = field(repr=False)
    openrouter_model: str
    openrouter_base_url: str
    reference_date: date
    data_dir: Path


def load_settings(
    env_file: Path | str | None = None,
    *,
    require_api_key: bool = True,
    override_env: bool = False,
) -> Settings:
    """Load and validate application settings from environment variables.

    Args:
        env_file: Optional path to a `.env` file. If omitted, `.env` in the current
            working directory is loaded when present.
        require_api_key: Whether to enforce a non-empty, non-placeholder API key.
        override_env: Whether values in `env_file` should override existing `os.environ` keys.

    Raises:
        ValueError: If any setting is missing or invalid.
    """
    if env_file is not None:
        load_dotenv(dotenv_path=Path(env_file), override=override_env)
    else:
        default_dotenv = Path(".env")
        if default_dotenv.is_file():
            load_dotenv(dotenv_path=default_dotenv, override=override_env)

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if require_api_key and (not api_key or api_key == PLACEHOLDER_KEY):
        raise ValueError(
            "OPENROUTER_API_KEY is required and must not be empty or the example placeholder. "
            "Set it in .env (see .env.example)."
        )

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
    if not model:
        raise ValueError("OPENROUTER_MODEL must not be empty.")
    if not model.endswith(":free"):
        raise ValueError("OPENROUTER_MODEL must be an explicit free model ending in ':free'.")

    base_url = os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL).strip()
    if not base_url:
        raise ValueError("OPENROUTER_BASE_URL must not be empty.")

    raw_ref_date = os.getenv("REFERENCE_DATE", DEFAULT_REFERENCE_DATE).strip()
    try:
        ref_date = date.fromisoformat(raw_ref_date)
    except ValueError as exc:
        raise ValueError(
            f"REFERENCE_DATE must be a valid ISO date (YYYY-MM-DD), got {raw_ref_date!r}."
        ) from exc

    raw_data_dir = os.getenv("DATA_DIR", DEFAULT_DATA_DIR).strip()
    if not raw_data_dir:
        raise ValueError("DATA_DIR must not be empty.")
    data_dir = Path(raw_data_dir).resolve()
    if not data_dir.is_dir():
        raise ValueError(f"DATA_DIR does not exist or is not a directory: {data_dir}")

    return Settings(
        openrouter_api_key=api_key,
        openrouter_model=model,
        openrouter_base_url=base_url,
        reference_date=ref_date,
        data_dir=data_dir,
    )
