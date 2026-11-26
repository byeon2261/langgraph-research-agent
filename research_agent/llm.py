"""채팅 모델 생성을 한 곳에서 관리한다.

추론(reasoning) 모델은 temperature를 받지 않는다. OpenAI GPT-6 가이드:
"When reasoning effort is not `none`, remove `temperature`, `top_p`, and `top_logprobs`."
그리고 GPT-6 Astra, GPT-6.1 Sol은 `none` 추론 강도를 지원하지 않는다.
langchain-openai는 gpt-5 계열만 temperature를 자동으로 빼 주므로 여기서 직접 처리한다.
"""
import os
import re

from langchain_openai import ChatOpenAI

# temperature 대신 추론 강도(reasoning_effort)를 쓰는 모델 이름 패턴
_REASONING = re.compile(r"^(o\d|gpt-5(?!-chat)|gpt-6)", re.IGNORECASE)


def is_reasoning_model(model: str) -> bool:
    return bool(_REASONING.match(model or ""))


def chat_kwargs(model: str, timeout: int = 60) -> dict:
    kwargs = {"model": model, "max_retries": 3, "timeout": timeout}
    if is_reasoning_model(model):
        # low: 가장 빠르고 저렴. 품질이 부족하면 .env에서 medium/high로 올린다
        kwargs["reasoning_effort"] = os.getenv("REASONING_EFFORT", "low")
        kwargs["timeout"] = max(timeout, 180)  # 추론 모델은 응답이 느릴 수 있음
    else:
        kwargs["temperature"] = 0
    return kwargs


def make_chat_model(model: str, timeout: int = 60) -> ChatOpenAI:
    return ChatOpenAI(**chat_kwargs(model, timeout))
