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
    """제목, 표 머리글·구분선, '확인되지 않음' 표시, 짧은 줄을 뺀 '주장이 담긴 줄'"""
    lines = [l.strip() for l in (report or "").splitlines()]
    out = []
    for i, t in enumerate(lines):
        if not t or t.startswith("#") or set(t) <= set("|-: "):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if t.startswith("|") and nxt and set(nxt) <= set("|-: "):
            continue  # 표 머리글 행
        if re.match(r"^[-*]\s*확인되지 않음", t):
            continue  # 근거가 없다고 밝힌 줄은 인용 대상이 아님
        if len(CITE_RE.sub("", t)) < 25:
            continue
        out.append(t)
    return out


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


def numeric_grounding(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """수치가 들어간 문장 중, 그 수치가 근거 자료에 같은 값·단위·맥락으로 있는 문장 비율.
    LLM 없이 코드로 계산하는 환각 지표 (규칙: research_agent/numbers.py). 수치 문장이 없으면 1점"""
    from research_agent.nodes import check_report_numbers
    from research_agent.numbers import REASON_KO

    total, bad = check_report_numbers(outputs.get("report", ""), outputs.get("evidence") or [])
    if total == 0:
        return {"key": "numeric_grounding", "score": 1.0, "comment": "수치 문장 없음"}
    comment = f"{total - len(bad)}/{total}문장"
    if bad:
        first = bad[0]
        comment += f" · 예: {first['numbers'][0]} ({REASON_KO[first['reasons'][0]]}) — {first['sentence'][:70]}"
    return {"key": "numeric_grounding", "score": round(1 - len(bad) / total, 3), "comment": comment}


def efficiency(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """비용·속도 관련 값 (점수가 아니라 측정값). 여러 값은 {"results": [...]}로 반환"""
    return {
        "results": [
            {"key": "num_searches", "score": outputs.get("num_searches", 0)},
            {"key": "num_rounds", "score": outputs.get("loop_count", 0)},
            {"key": "latency_sec", "score": round(outputs.get("latency_sec", 0.0), 1)},
            {"key": "revised_sentences", "score": outputs.get("revised_sentences", 0)},
        ]
    }


# ---------- LLM 심판 지표 (gpt-4o 호출) ----------
class AspectJudgement(BaseModel):
    covered: list[bool] = Field(description="각 관점이 보고서에 구체적으로 다뤄졌으면 true (같은 순서)")
    reason: str = Field(description="빠진 관점과 이유를 한두 문장으로")


class ExtractedClaim(BaseModel):
    quote: str = Field(description="보고서 문장을 한 글자도 바꾸지 않고 그대로 옮긴 것")
    cited: list[int] = Field(description="그 문장에 붙은 출처 번호. 없으면 빈 목록")


class ClaimExtraction(BaseModel):
    claims: list[ExtractedClaim] = Field(description="구체적인 주장 최대 12개")


class ClaimVerdicts(BaseModel):
    verdicts: list[str] = Field(description="주장 순서대로 supported / partial / unsupported 중 하나")
    reasons: list[str] = Field(description="주장 순서대로, 판정 이유 한 문장")


ASPECT_PROMPT = """당신은 리서치 보고서를 채점하는 심판입니다.
아래 '꼭 다뤄야 할 관점' 각각이 보고서에 구체적인 내용(수치, 고유명사, 사례 등)으로 다뤄졌는지 판단하세요.
관점을 언급만 하고 "확인되지 않음"이라고 쓴 경우는 false입니다.

질문: {question}

꼭 다뤄야 할 관점:
{aspects}

보고서:
{report}"""

# 근거 일치율 심판은 두 단계로 나눈다 (2026-11-26 평가에서 심판이 근거 자료 문장을 보고서 주장으로
# 착각해 채점하는 오류를 발견 → 1단계에서는 근거 자료를 아예 보여 주지 않는다)
EXTRACT_PROMPT = """아래 리서치 보고서에서 수치, 날짜, 고유명사, 비교가 들어간 구체적인 주장 문장을 최대 12개 고르세요.
- 보고서에 실제로 있는 문장만 고르고, quote에는 보고서 문장을 한 글자도 바꾸지 말고 그대로 옮기세요.
- 출처 번호가 없는 구체적인 주장도 포함하세요.
- 표에 있는 주장은 그 행을 `| ... |` 원문 그대로 quote에 옮기세요. 여러 행을 합치거나 문장으로 바꿔 쓰지 마세요.
- cited에는 그 문장(행)에 붙은 [번호]를 적으세요.

보고서:
{report}"""

VERIFY_PROMPT = """당신은 리서치 보고서의 엄격한 사실 확인 담당자입니다.
아래 각 주장이 근거 자료로 뒷받침되는지 판정하세요. 주장마다 그 주장이 인용한 근거 자료가 함께 주어집니다.
- supported: 근거 자료에 같은 내용이 있고, 수치·날짜·이름이 정확히 일치함
- partial: 대체로 맞지만 수치·날짜·대상이 다르거나, 근거보다 과장·일반화됨
- unsupported: 근거 자료에 없음, 또는 출처 번호가 없는데 전체 근거 자료 어디에도 없음
애매하면 더 낮은 판정을 고르세요. verdicts와 reasons는 주장 개수와 같은 길이여야 합니다.

{claims}"""


def _norm_text(t: str) -> str:
    return re.sub(r"[\s\[\]\d.,·()\"'“”‘’:;!?~\-|*_`]", "", CITE_RE.sub("", t or ""))


def _bigrams(t: str) -> set[str]:
    return {t[i:i + 2] for i in range(len(t) - 1)}


def claim_in_report(quote: str, report: str, min_overlap: float = 0.7) -> bool:
    """심판이 뽑은 주장이 정말 보고서에 있는지 코드로 확인한다.
    1) 글자(공백·숫자·기호 제외)가 보고서 문장과 70% 이상 겹치고
    2) 주장에 든 수치가 모두 보고서에도 있어야 한다"""
    from research_agent.nodes import _report_sentences
    from research_agent.numbers import extract_mentions, is_checkable, values_match

    q = _norm_text(quote)
    if not q:
        return False
    qb = _bigrams(q)
    best = 0.0
    for sent in _report_sentences(report):
        sn = _norm_text(sent)
        if q in sn:
            best = 1.0
            break
        if qb:
            best = max(best, len(qb & _bigrams(sn)) / len(qb))
            # 표의 행은 심판이 문장으로 풀어 쓰기 쉬우므로, 행 내용이 주장에 대부분 들어 있으면 인정
            sb = _bigrams(sn)
            if sent.startswith("|") and sb:
                best = max(best, len(qb & sb) / len(sb))
    if best < min_overlap:
        return False
    report_nums = [m for m in extract_mentions(report) if is_checkable(m)]
    for m in (x for x in extract_mentions(quote) if is_checkable(x)):
        if not any(values_match(m, r) or values_match(r, m) for r in report_nums):
            return False
    return True


def _judge_llm():
    from research_agent.llm import make_chat_model

    return make_chat_model(os.getenv("JUDGE_MODEL", "gpt-4o"), timeout=90)


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
        """보고서의 구체적 주장이 실제 근거 자료로 뒷받침되는 정도 (환각 점검)
        1단계: 보고서만 보고 주장 추출 → 코드로 '정말 보고서에 있는 주장인지' 확인
        2단계: 주장마다 인용한 근거 자료만 붙여서 판정"""
        evidence = outputs.get("evidence") or []
        report = outputs.get("report") or ""
        if not report or not evidence:
            return {"key": "groundedness", "score": 0.0, "comment": "보고서 또는 근거 없음"}

        extracted = judge.with_structured_output(ClaimExtraction).invoke(EXTRACT_PROMPT.format(report=report))
        claims = [c for c in extracted.claims if claim_in_report(c.quote, report)]
        dropped = len(extracted.claims) - len(claims)
        if not claims:
            return {"key": "groundedness", "score": 0.0, "comment": f"검사할 주장 없음 (심판 오류로 제외 {dropped}건)"}

        by_n = {e["n"]: e for e in evidence}
        blocks = []
        for i, c in enumerate(claims, 1):
            src = [by_n[n] for n in c.cited if n in by_n] or evidence  # 출처 없으면 전체 자료
            ev_text = "\n".join(f"  [{e['n']}] {e.get('title', '')}: {e.get('content', '')}" for e in src)
            blocks.append(f"주장 {i}: {c.quote}\n근거 자료:\n{ev_text}")
        res = judge.with_structured_output(ClaimVerdicts).invoke(VERIFY_PROMPT.format(claims="\n\n".join(blocks)))
        verdicts = [v.strip().lower() for v in res.verdicts] + ["unsupported"] * len(claims)
        verdicts = verdicts[: len(claims)]

        points = {"supported": 1.0, "partial": 0.5}
        score = sum(points.get(v, 0.0) for v in verdicts) / len(claims)
        bad = [f"({v}) {c.quote}" for c, v in zip(claims, verdicts) if v != "supported"]
        note = f" · 심판 오류로 제외 {dropped}건" if dropped else ""
        return {
            "key": "groundedness",
            "score": round(score, 3),
            "comment": (("근거 부족: " + " / ".join(bad[:5])) if bad else f"{len(claims)}개 주장 모두 근거 있음") + note,
        }

    return [aspect_coverage, groundedness]


RULE_EVALUATORS = [numeric_grounding, citation_validity, citation_coverage, subq_coverage, source_diversity, efficiency]

# 요약표에 보여 줄 순서 (위: 품질 점수 0~1, 아래: 측정값)
QUALITY_KEYS = [
    "aspect_coverage",
    "groundedness",
    "numeric_grounding",
    "citation_validity",
    "citation_coverage",
    "subq_coverage",
    "source_diversity",
]
MEASURE_KEYS = ["num_searches", "num_rounds", "latency_sec", "revised_sentences"]
