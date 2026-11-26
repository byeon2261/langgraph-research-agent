"""모델별 호출 옵션 테스트 (research_agent/llm.py)"""
import pytest

from research_agent.llm import chat_kwargs, is_reasoning_model, make_chat_model


@pytest.mark.parametrize(
    "model,reasoning",
    [
        ("gpt-4o-mini", False),
        ("gpt-4o", False),
        ("gpt-4.1", False),
        ("gpt-5-chat-latest", False),
        ("gpt-6.1-sol", True),
        ("gpt-6-astra", True),
        ("gpt-5", True),
        ("o3", True),
        ("o4-mini", True),
    ],
)
def test_is_reasoning_model(model, reasoning):
    assert is_reasoning_model(model) is reasoning


def test_reasoning_model_drops_temperature(monkeypatch):
    monkeypatch.delenv("REASONING_EFFORT", raising=False)
    k = chat_kwargs("gpt-6.1-sol")
    assert "temperature" not in k and k["reasoning_effort"] == "low" and k["timeout"] >= 180


def test_reasoning_effort_from_env(monkeypatch):
    monkeypatch.setenv("REASONING_EFFORT", "medium")
    assert chat_kwargs("gpt-6.1-sol")["reasoning_effort"] == "medium"


def test_normal_model_keeps_temperature_zero():
    k = chat_kwargs("gpt-4o-mini")
    assert k["temperature"] == 0 and "reasoning_effort" not in k


def test_request_payload_has_no_temperature_for_sol(monkeypatch):
    """실제 OpenAI 요청 본문에 temperature가 빠지는지 확인 (네트워크 호출 없음)"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    payload = make_chat_model("gpt-6.1-sol")._get_request_payload("hi")
    assert "temperature" not in payload and payload["reasoning_effort"] == "low"
    payload = make_chat_model("gpt-4o-mini")._get_request_payload("hi")
    assert payload["temperature"] == 0
