"""리서치 결과 품질 지표.

모든 평가 함수는 LangSmith evaluate()와 로컬 실행에서 똑같이 쓰이도록
(outputs, reference_outputs) 인자를 받고 {"key", "score", "comment"}를 돌려준다.
score는 0~1 (높을수록 좋음). 효율 지표(num_searches 등)는 그대로의 값이다.
"""
import os
import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

CITE_RE = re.compile(r"\[(\d+)\]")


def _cited(report: str) -> set[int]:
    return {int(x) for x in CITE_RE.findall(report or "")}


def _content_lines(report: str) -> list[str]:
    """제목, 표 구분선, 짧은 줄을 뺀 '주장이 담긴 줄'"""
    lines = []
    for line in (report or "").splitlines():
        t = line.strip()
        if not t or t.startswith("#") or set(t) <= set("|-: "):
            continue
        if len(CITE_RE.sub("", t)) < 25:
            continue
        lines.append(t)
    return lines


# ---------- 규칙 기반 지표 (비용 0) ----------
def citation_validity(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """보고서의 [번호]가 실제 출처 목록에 있는 비율. 인용이 하나도 없으면 0"""
    cited = _cited(outputs.get("report", ""))
    valid = {s["n"] for s in outputs.get("sources", [])}
    if not cited:
        return {"key": "citation_validity", "score": 0.0, "comment": "인용 없음"}
    bad = sorted(cited - valid)
    return {
        "key": "citation_validity",
        "score": round(len(cited & valid) / len(cited), 3),
        "comment": f"잘못된 번호: {bad}" if bad else "모두 유효",
    }


def citation_coverage(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """주장이 담긴 줄 중 출처 [번호]가 붙은 줄의 비율"""
    lines = _content_lines(outputs.get("report", ""))
    if not lines:
        return {"key": "citation_coverage", "score": 0.0, "comment": "본문 없음"}
    with_cite = sum(1 for t in lines if CITE_RE.search(t))
    return {"key": "citation_coverage", "score": round(with_cite / len(lines), 3), "comment": f"{with_cite}/{len(lines)}줄"}


def subq_coverage(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """에이전트 스스로 판단한 하위 질문 근거 확보율 (covered의 평균)"""
    covered = outputs.get("covered") or []
    score = sum(covered) / len(covered) if covered else 0.0
    return {"key": "subq_coverage", "score": round(score, 3), "comment": f"{sum(covered)}/{len(covered)}"}


def source_diversity(outputs: dict, reference_outputs: dict | None = None, target: int = 6) -> dict:
    """서로 다른 출처 도메인 수 (target개 이상이면 1점)"""
    domains = {urlparse(s.get("url", "")).netloc.removeprefix("www.") for s in outputs.get("sources", [])}
    domains.discard("")
    return {"key": "source_diversity", "score": round(min(len(domains) / target, 1.0), 3), "comment": f"{len(domains)}개 도메인"}


def efficiency(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """비용·속도 관련 값 (점수가 아니라 측정값). 여러 값은 {"results": [...]}로 반환"""
    return {
        "results": [
            {"key": "num_searches", "score": outputs.get("num_searches", 0)},
            {"key": "num_rounds", "score": outputs.get("loop_count", 0)},
            {"key": "latency_sec", "score": round(outputs.get("latency_sec", 0.0), 1)},
        ]
    }


# ---------- LLM 심판 지표 (gpt-4o 호출) ----------
class AspectJudgement(BaseModel):
    covered: list[bool] = Field(description="각 관점이 보고서에 구체적으로 다뤄졌으면 true (같은 순서)")
    reason: str = Field(description="빠진 관점과 이유를 한두 문장으로")


class ClaimCheck(BaseModel):
    claim: str = Field(description="보고서의 구체적인 주장 (수치, 날짜, 고유명사가 들어간 문장 우선)")
    cited: list[int] = Field(description="주장에 붙은 출처 번호. 없으면 빈 목록")
    verdict: str = Field(description="supported / partial / unsupported 중 하나")


class GroundednessJudgement(BaseModel):
    claims: list[ClaimCheck] = Field(description="구체적인 주장 최대 12개")


ASPECT_PROMPT = """당신은 리서치 보고서를 채점하는 심판입니다.
아래 '꼭 다뤄야 할 관점' 각각이 보고서에 구체적인 내용(수치, 고유명사, 사례 등)으로 다뤄졌는지 판단하세요.
관점을 언급만 하고 "확인되지 않음"이라고 쓴 경우는 false입니다.

질문: {question}

꼭 다뤄야 할 관점:
{aspects}

보고서:
{report}"""

GROUNDED_PROMPT = """당신은 리서치 보고서의 엄격한 사실 확인 담당자입니다.
보고서에서 수치, 날짜, 고유명사, 비교가 들어간 구체적인 주장을 최대 12개 고르세요.
출처 번호가 없는 구체적인 주장도 포함하세요.
각 주장을 다음 기준으로 판정하세요.
- supported: 붙은 번호의 근거 자료에 같은 내용이 있고, 수치·날짜·이름이 정확히 일치함
- partial: 대체로 맞지만 수치·날짜·대상이 다르거나, 근거보다 과장·일반화됨
- unsupported: 근거 자료에 없음, 다른 번호의 자료에만 있음, 또는 출처 번호가 없음
애매하면 더 낮은 판정을 고르세요.

보고서:
{report}

근거 자료:
{evidence}"""


def _judge_llm():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=os.getenv("JUDGE_MODEL", "gpt-4o"), temperature=0, max_retries=3, timeout=90)


def make_llm_judges(judge=None):
    """judge: with_structured_output을 지원하는 채팅 모델 (기본 gpt-4o)"""
    judge = judge or _judge_llm()

    def aspect_coverage(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        """사람이 정한 '꼭 다뤄야 할 관점'을 보고서가 다룬 비율"""
        aspects = (reference_outputs or {}).get("aspects") or []
        if not aspects:
            return {"key": "aspect_coverage", "score": None, "comment": "관점 없음"}
        res = judge.with_structured_output(AspectJudgement).invoke(
            ASPECT_PROMPT.format(
                question=inputs["question"],
                aspects="\n".join(f"{i}. {a}" for i, a in enumerate(aspects, 1)),
                report=outputs.get("report", ""),
            )
        )
        cov = (list(res.covered) + [False] * len(aspects))[: len(aspects)]
        return {"key": "aspect_coverage", "score": round(sum(cov) / len(aspects), 3), "comment": res.reason}

    def groundedness(outputs: dict) -> dict:
        """인용된 주장이 실제 근거 자료로 뒷받침되는 비율 (환각 점검)"""
        evidence = outputs.get("evidence") or []
        if not outputs.get("report") or not evidence:
            return {"key": "groundedness", "score": 0.0, "comment": "보고서 또는 근거 없음"}
        res = judge.with_structured_output(GroundednessJudgement).invoke(
            GROUNDED_PROMPT.format(
                report=outputs["report"],
                evidence="\n\n".join(f"[{e['n']}] {e.get('title', '')}\n{e.get('content', '')}" for e in evidence),
            )
        )
        if not res.claims:
            return {"key": "groundedness", "score": 0.0, "comment": "검사할 주장 없음"}
        # supported 1점, partial 0.5점, unsupported 0점
        points = {"supported": 1.0, "partial": 0.5}
        score = sum(points.get(c.verdict.strip().lower(), 0.0) for c in res.claims) / len(res.claims)
        bad = [f"({c.verdict}) {c.claim}" for c in res.claims if c.verdict.strip().lower() != "supported"]
        return {
            "key": "groundedness",
            "score": round(score, 3),
            "comment": ("근거 부족: " + " / ".join(bad[:3])) if bad else f"{len(res.claims)}개 주장 모두 근거 있음",
        }

    return [aspect_coverage, groundedness]


RULE_EVALUATORS = [citation_validity, citation_coverage, subq_coverage, source_diversity, efficiency]

# 요약표에 보여 줄 순서 (위: 품질 점수 0~1, 아래: 측정값)
QUALITY_KEYS = [
    "aspect_coverage",
    "groundedness",
    "citation_validity",
    "citation_coverage",
    "subq_coverage",
    "source_diversity",
]
MEASURE_KEYS = ["num_searches", "num_rounds", "latency_sec"]
