import pytest

from src.core.config import Settings, validate_llm_settings


def test_fake_provider_does_not_require_gemini_secret():
    validate_llm_settings(Settings(LLM_PROVIDER="fake", GEMINI_API_KEY=None))


def test_gemini_provider_requires_key_at_startup():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        validate_llm_settings(Settings(LLM_PROVIDER="gemini", GEMINI_API_KEY=None))


def test_openai_provider_requires_key_at_startup():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        validate_llm_settings(Settings(LLM_PROVIDER="openai", OPENAI_API_KEY=None))
