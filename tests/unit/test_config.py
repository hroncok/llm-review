import pytest

from llm_review.config import ConfigError, load_backend_config


def test_default_backend_is_vertex():
    env = {
        "ANTHROPIC_VERTEX_PROJECT_ID": "my-project",
        "CLOUD_ML_REGION": "us-east5",
    }
    config = load_backend_config(env)
    assert config.backend == "vertex"
    assert config.env == {
        "CLAUDE_CODE_USE_VERTEX": "1",
        "CLOUD_ML_REGION": "us-east5",
        "ANTHROPIC_VERTEX_PROJECT_ID": "my-project",
    }
    assert config.model is None


def test_vertex_missing_env_vars_raises():
    with pytest.raises(ConfigError):
        load_backend_config({})


def test_bedrock_backend():
    env = {"LLM_REVIEW_BACKEND": "bedrock", "AWS_REGION": "us-east-1"}
    config = load_backend_config(env)
    assert config.backend == "bedrock"
    assert config.env == {
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_REGION": "us-east-1",
    }


def test_bedrock_missing_env_vars_raises():
    with pytest.raises(ConfigError):
        load_backend_config({"LLM_REVIEW_BACKEND": "bedrock"})


def test_unknown_backend_raises():
    with pytest.raises(ConfigError):
        load_backend_config({"LLM_REVIEW_BACKEND": "openai"})


def test_model_override_is_passed_through():
    env = {
        "ANTHROPIC_VERTEX_PROJECT_ID": "my-project",
        "CLOUD_ML_REGION": "us-east5",
        "LLM_REVIEW_MODEL": "claude-opus-5",
    }
    config = load_backend_config(env)
    assert config.model == "claude-opus-5"


def test_backend_is_case_insensitive():
    env = {
        "LLM_REVIEW_BACKEND": "VERTEX",
        "ANTHROPIC_VERTEX_PROJECT_ID": "my-project",
        "CLOUD_ML_REGION": "us-east5",
    }
    config = load_backend_config(env)
    assert config.backend == "vertex"
