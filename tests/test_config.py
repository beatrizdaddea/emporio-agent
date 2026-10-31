"""Tests for emporio.config."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from emporio.config import (
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_OPENROUTER_MODEL,
    PLACEHOLDER_KEY,
    load_settings,
)

ENV_KEYS = (
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENROUTER_BASE_URL",
    "REFERENCE_DATE",
    "DATA_DIR",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_settings_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-123")

    settings = load_settings(env_file=empty_env)

    assert settings.openrouter_api_key == "sk-or-test-123"
    assert settings.openrouter_model == DEFAULT_OPENROUTER_MODEL
    assert settings.openrouter_base_url == DEFAULT_OPENROUTER_BASE_URL
    assert settings.reference_date == date(2026, 3, 23)
    assert settings.data_dir.is_dir()
    assert settings.data_dir.name == "data"


def test_load_settings_from_env_file(tmp_path: Path) -> None:
    custom_data = tmp_path / "custom_data"
    custom_data.mkdir()
    env_file = tmp_path / "custom.env"
    env_file.write_text(
        "\n".join(
            [
                "OPENROUTER_API_KEY=sk-or-from-file",
                "OPENROUTER_MODEL=google/gemma-3-27b-it:free",
                "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1",
                "REFERENCE_DATE=2026-04-01",
                f"DATA_DIR={custom_data}",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file, override_env=True)

    assert settings.openrouter_api_key == "sk-or-from-file"
    assert settings.openrouter_model == "google/gemma-3-27b-it:free"
    assert settings.reference_date == date(2026, 4, 1)
    assert settings.data_dir == custom_data.resolve()


def test_missing_or_placeholder_api_key_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_settings(env_file=empty_env, require_api_key=True)

    monkeypatch.setenv("OPENROUTER_API_KEY", PLACEHOLDER_KEY)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_settings(env_file=empty_env, require_api_key=True)


def test_require_api_key_false_allows_missing_key(tmp_path: Path) -> None:
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")

    settings = load_settings(env_file=empty_env, require_api_key=False)
    assert settings.openrouter_api_key == ""


def test_invalid_reference_date_raises(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENROUTER_API_KEY=sk-or-test\nREFERENCE_DATE=23/03/2026\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="REFERENCE_DATE"):
        load_settings(env_file=env_file, override_env=True)


def test_missing_data_dir_raises(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"OPENROUTER_API_KEY=sk-or-test\nDATA_DIR={tmp_path / 'does_not_exist'}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="DATA_DIR"):
        load_settings(env_file=env_file, override_env=True)
