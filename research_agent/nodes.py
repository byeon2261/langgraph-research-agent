import logging
import os
import re
import time
from dataclasses import dataclass, field, fields
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlparse

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from research_agent.prompts import (
    EVALUATE_PROMPT,
    FOLLOWUP_PROMPT,
    PLAN_PROMPT,
    REPORT_PROMPT,
    REVISE_PROMPT,
)
from research_agent.numbers import REASON_KO, check_sentence
from research_agent.state import SearchState, State

load_dotenv()
log = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """실행 설정. 기본값은 .env, 실행할 때 config["configurable"]로 덮어쓸 수 있다.
    예) graph.invoke(inputs, {"configurable": {"max_loops": 1, "eval_model": "gpt-4o-mini"}})
    """

    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    eval_model: str = field(default_factory=lambda: os.getenv("EVAL_MODEL", "gpt-4o"))
    report_model: str = field(
        default_factory=lambda: os.getenv("REPORT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    )
    max_loops: int = field(default_factory=lambda: _env_int("MAX_LOOPS", 3))
    min_domains: int = field(default_factory=lambda: _env_int("MIN_DOMAINS", 3))
    min_results_per_subq: int = field(default_factory=lambda: _env_int("MIN_RESULTS_PER_SUBQ", 2))
    # 토큰 관리: 결과 본문 길이 + 하위 질문당 프롬프트에 넣을 결과 수 제한
    max_content_chars: int = field(default_factory=lambda: _env_int("MAX_CONTENT_CHARS", 800))
    max_results_per_subq_in_prompt: int = field(
        default_factory=lambda: _env_int("MAX_RESULTS_PER_SUBQ_IN_PROMPT", 6)
    )
    search_retries: int = field(default_factory=lambda: _env_int("SEARCH_RETRIES", 2))
    # False면 질문을 쪼개지 않고 원래 질문 하나로 검색 (평가에서 질문 분해 효과 측정용)
    use_plan: bool = True
    # True면 보고서 작성 후 수치가 근거 자료에 있는지 검사하고, 없는 문장만 고친다
    verify_report: bool = True


def get_settings(config: RunnableConfig | None = None) -> Settings:
    overrides = (config or {}).get("configurable", {})
    names = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in overrides.items() if k in names})


DEFAULTS = Settings()

# OpenAI 호출: 실패 시 자동 재시도 + 타임아웃
_llm_opts = dict(temperature=0, max_retries=3, timeout=60)


@lru_cache(maxsize=None)
def _chat(model: str) -> ChatOpenAI:
    return ChatOpenAI(model=model, **_llm_opts)


# 기본 모델 (테스트에서 가짜 모델로 바꿔 끼운다)
llm = _chat(DEFAULTS.model)
eval_llm = _chat(DEFAULTS.eval_model)
report_llm = _chat(DEFAULTS.report_model)
search_tool = TavilySearch(max_results=_env_int("SEARCH_MAX_RESULTS", 3))


def _model(role: str, s: Settings):
    """설정한 모델이 기본값이면 모듈 전역 모델을, 다르면 해당 모델을 쓴다"""
    default_obj = {"model": llm, "eval_model": eval_llm, "report_model": report_llm}[role]
    name = getattr(s, role)
    return default_obj if name == getattr(DEFAULTS, role) else _chat(name)


# ---------- 공통 유틸 ----------
def _today() -> str:
    # 로컬 시간 기준 오늘 날짜 (tz 데이터베이스 없이 동작)
    now = datetime.now().astimezone()
    return now.strftime("%Y년 %m월 %d일")


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.removeprefix("www.")


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {q}" for i, q in enumerate(items, 1))


def _numbered_with_status(state: State) -> str:
    """보고서 프롬프트용: 하위 질문마다 평가 결과(근거 확보/부족)를 붙인다"""
    subs, covered = state.get("sub_questions", []), state.get("covered") or []
    lines = []
    for i, q in enumerate(subs, 1):
        ok = covered[i - 1] if i - 1 < len(covered) else True
        lines.append(f"{i}. {q} {'[근거 확보]' if ok else '[근거 부족]'}")
    return "\n".join(lines)


def _select(state: State, s: Settings = DEFAULTS) -> list[dict]:
    """프롬프트에 넣을 결과를 고른다. 이 목록의 순서가 곧 보고서의 [번호]이자 sources의 번호다.
    - 현재 질문(turn)의 현재 하위 질문 결과만 사용
    - URL 중복 제거
    - 하위 질문당 최대 N건. 넘치면 **최근 라운드(재검색) 결과를 우선** 남긴다
      (재검색은 '근거가 부족하다'고 판정된 뒤에 한 것이므로 새 결과가 더 필요한 자료다)
    - 출력 순서는 하위 질문 순서 → 라운드 → 수집 순서로 고정
    """
    subs = state.get("sub_questions", [])
    turn = state.get("current_turn")
    seen, by_sub = set(), {q: [] for q in subs}
    for i, r in enumerate(state.get("results", [])):
        q, url = r.get("sub_question"), r.get("url")
        if q not in by_sub or not url or url in seen:
            continue
        if turn is not None and r.get("turn", turn) != turn:
            continue
        seen.add(url)
        by_sub[q].append((r.get("round", 1), i, r))

    out = []
    for q in subs:
        items = by_sub[q]
        keep = sorted(items, key=lambda x: (-x[0], x[1]))[: s.max_results_per_subq_in_prompt]
        out.extend(r for _, _, r in sorted(keep, key=lambda x: (x[0], x[1])))
    return out


def _format_results(results: list[dict]) -> str:
    lines = [
        f"[{i}] {r.get('title', '')}\nURL: {r.get('url', '')}\n"
        f"(하위 질문: {r.get('sub_question', '')})\n{r.get('content', '')}\n"
        for i, r in enumerate(results, 1)
    ]
    return "\n".join(lines) if lines else "(없음)"



# ---------- plan: 질문을 하위 질문으로 쪼개기 ----------
class PlanItem(BaseModel):
    sub_question: str = Field(description="조사할 하위 질문")
    query: str = Field(description="이 하위 질문용 웹 검색어")


class Plan(BaseModel):
    items: list[PlanItem] = Field(description="하위 질문 3~4개")


def plan(state: State, config: RunnableConfig) -> dict:
    s = get_settings(config)
    past = state.get("past_questions", [])
    turn = len(past) + 1
    if s.use_plan:
        prev_report = (state.get("report") or "")[:1000] or "(없음)"
        result = _model("model", s).with_structured_output(Plan).invoke(
            PLAN_PROMPT.format(
                today=_today(),
                question=state["question"],
                past_questions=" / ".join(past) or "(없음)",
                previous_report=prev_report,
            )
        )
        items = [(it.sub_question, it.query) for it in result.items[:4]]
    else:
        items = [(state["question"], state["question"])]  # 질문 그대로 한 번 검색
    return {
        "past_questions": [state["question"]],
        "current_turn": turn,
        "sub_questions": [sq for sq, _ in items],
        "pending_queries": [{"query": q, "sub_question": sq, "round": 1, "turn": turn} for sq, q in items],
        "loop_count": 1,
        "max_loops": s.max_loops,
        # 새 질문이 시작되면 이전 평가/보고서 상태는 초기화
        "covered": [],
        "rule_notes": [],
        "is_sufficient": False,
        "missing_info": "",
    }


# ---------- review_plan: 검색 전에 사용자 승인/수정 (interrupt) ----------
def review_plan(state: State) -> dict:
    tasks = state.get("pending_queries", [])
    if state.get("review"):
        # 실행이 여기서 멈추고, Command(resume=...)로 값을 받으면 이 줄부터 다시 실행된다
        answer = interrupt(
            {
                "type": "review_plan",
                "message": "검색할 하위 질문을 확인하세요. 수정하거나 그대로 승인할 수 있어요.",
                "sub_questions": [t["sub_question"] for t in tasks],
                "queries": [t["query"] for t in tasks],
            }
        )
        edited = answer.get("sub_questions") if isinstance(answer, dict) else None
        if edited:
            by_sub = {t["sub_question"]: t["query"] for t in tasks}
            edited = [s.strip() for s in edited if s and s.strip()][:6]
            # 바뀌지 않은 하위 질문은 원래 검색어를, 새로 쓴 하위 질문은 그 문장을 검색어로 사용
            turn = state.get("current_turn")
            tasks = [{"sub_question": s, "query": by_sub.get(s, s), "round": 1, "turn": turn} for s in edited]
    return {
        "sub_questions": [t["sub_question"] for t in tasks],
        "pending_queries": tasks,
        "queries": [t["query"] for t in tasks],
    }


# ---------- 재검색: 근거가 없는 하위 질문만 다시 검색어 생성 ----------
class FollowUpItem(BaseModel):
    sub_question_no: int = Field(description="근거가 부족한 하위 질문 목록의 번호 (1부터)")
    query: str = Field(description="새 검색어")


class FollowUp(BaseModel):
    items: list[FollowUpItem] = Field(description="새 검색어 (최대 3개)")


def generate_query(state: State, config: RunnableConfig) -> dict:
    s = get_settings(config)
    subs = state.get("sub_questions", [])
    covered = state.get("covered", [])
    uncovered = [q for q, ok in zip(subs, covered) if not ok] or subs
    result = _model("model", s).with_structured_output(FollowUp).invoke(
        FOLLOWUP_PROMPT.format(
            today=_today(),
            question=state["question"],
            uncovered=_numbered(uncovered),
            missing_info=state.get("missing_info") or "(없음)",
            queries=", ".join(state.get("queries", [])) or "(없음)",
        )
    )
    tasks = []
    for it in result.items[:3]:
        # 번호로 원래 하위 질문 문장에 정확히 연결 (LLM이 문장을 바꿔 써도 안전)
        idx = min(max(it.sub_question_no, 1), len(uncovered)) - 1
        tasks.append({
            "query": it.query,
            "sub_question": uncovered[idx],
            "round": state.get("loop_count", 0) + 1,
            "turn": state.get("current_turn"),
        })
    return {
        "pending_queries": tasks,
        "queries": [t["query"] for t in tasks],
        "loop_count": state.get("loop_count", 0) + 1,
    }


# ---------- search: Send로 검색어마다 병렬 실행 ----------
def search(state: SearchState, config: RunnableConfig) -> dict:
    s = get_settings(config)
    query = state["query"]
    last_error = None
    for attempt in range(s.search_retries + 1):  # 재시도
        try:
            response = search_tool.invoke({"query": query})
            break
        except Exception as e:  # noqa: BLE001
            last_error = e
            log.warning("search failed (%s/%s): %s", attempt + 1, s.search_retries + 1, e)
            time.sleep(1.5 * (attempt + 1))
    else:
        # 끝내 실패하면 그래프를 멈추지 않고 빈 결과로 넘어간다 (평가에서 재검색 대상이 됨)
        return {"results": [], "search_errors": [f"'{query}': {last_error}"]}

    items = response.get("results", []) if isinstance(response, dict) else []
    results = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "content": (r.get("content") or "")[: s.max_content_chars],
            "query": query,
            "sub_question": state["sub_question"],
            "round": state.get("round", 1),
            "turn": state.get("turn"),
        }
        for r in items
    ]
    return {"results": results}


# ---------- evaluate: 강한 모델 + 규칙 점검 + 근거 기록 ----------
class Evaluation(BaseModel):
    covered: list[bool] = Field(description="하위 질문별 구체적 근거 여부 (같은 순서)")
    missing_info: str = Field(description="근거가 없는 하위 질문과 더 찾을 내용. 충분하면 빈 문자열")


def evaluate(state: State, config: RunnableConfig) -> dict:
    s = get_settings(config)
    subs = state.get("sub_questions", [])
    selected = _select(state, s)

    result = _model("eval_model", s).with_structured_output(Evaluation).invoke(
        EVALUATE_PROMPT.format(
            today=_today(),
            question=state["question"],
            sub_questions=_numbered(subs),
            results=_format_results(selected),
        )
    )
    covered = (list(result.covered) + [False] * len(subs))[: len(subs)]

    notes: list[str] = []
    domains = {_domain(r["url"]) for r in selected}
    if len(domains) < s.min_domains:
        notes.append(f"출처 도메인 {len(domains)}개 (최소 {s.min_domains}개 필요)")
    for i, q in enumerate(subs):
        n = sum(1 for r in selected if r.get("sub_question") == q)
        if n < s.min_results_per_subq:
            covered[i] = False
            notes.append(f"'{q}' 검색 결과 {n}건 (최소 {s.min_results_per_subq}건 필요)")

    is_sufficient = bool(subs) and all(covered) and not notes
    missing = result.missing_info
    if notes:
        missing = (missing + " / " if missing else "") + "규칙 점검: " + "; ".join(notes)

    return {
        "covered": covered,
        "rule_notes": notes,
        "is_sufficient": is_sufficient,
        "missing_info": "" if is_sufficient else missing,
    }


# ---------- write_report: 보고서와 같은 번호의 sources를 함께 반환 ----------
def write_report(state: State, config: RunnableConfig) -> dict:
    s = get_settings(config)
    selected = _select(state, s)
    report = _model("report_model", s).invoke(
        REPORT_PROMPT.format(
            today=_today(),
            question=state["question"],
            sub_questions=_numbered_with_status(state),
            missing_info=state.get("missing_info") or "(없음)",
            results=_format_results(selected),
        )
    ).content
    sources = [
        {"n": i, "title": r.get("title"), "url": r.get("url"), "sub_question": r.get("sub_question")}
        for i, r in enumerate(selected, 1)
    ]
    return {"report": report, "sources": sources}


# ---------- verify_report: 보고서의 수치가 근거 자료에 있는지 검사 ----------
_CITE = re.compile(r"\[(\d+)\]")
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+")


def _report_sentences(report: str):
    for line in (report or "").splitlines():
        t = line.strip()
        if not t or t.startswith("#") or set(t) <= set("|-: "):
            continue
        for sent in _SENT_SPLIT.split(t):
            if sent.strip():
                yield sent.strip()


def check_report_numbers(report: str, evidence: list[dict]) -> tuple[int, list[dict]]:
    """보고서의 수치 문장을 검사한다. 반환: (수치가 있는 문장 수, 문제 문장 목록)
    - 출처 번호가 붙은 문장: 그 번호의 근거 자료와 비교 (다른 자료에만 있으면 잘못된 인용)
    - 출처 번호가 없는 문장(요약 등): 전체 근거 자료와 비교
    - 값(반올림 허용)·단위·맥락이 모두 맞아야 통과 (자세한 규칙은 research_agent/numbers.py)
    evidence: [{"n": 번호, "content": 본문}, ...] (보고서 [번호]와 같은 순서)
    """
    by_n = {e["n"]: e.get("content") or "" for e in evidence}
    total, flagged = 0, []
    for sent in _report_sentences(report):
        cited = [int(c) for c in _CITE.findall(sent)]
        texts = [by_n[c] for c in cited if c in by_n] if cited else list(by_n.values())
        n_claims, issues = check_sentence(_CITE.sub("", sent), texts)
        if n_claims:
            total += 1
        if issues:
            flagged.append({
                "sentence": sent,
                "numbers": [i.text for i in issues],
                "reasons": [i.reason for i in issues],
                "cited": cited,
            })
    return total, flagged


def find_unsupported_numbers(report: str, evidence: list[dict]) -> list[dict]:
    """근거 자료로 확인되지 않는 수치가 들어간 문장 목록"""
    return check_report_numbers(report, evidence)[1]


def verify_report(state: State, config: RunnableConfig) -> dict:
    s = get_settings(config)
    if not s.verify_report:
        return {"unverified_claims": [], "revised_sentences": 0}
    selected = _select(state, s)
    evidence = [{"n": i, "content": r.get("content")} for i, r in enumerate(selected, 1)]
    report = state.get("report", "")
    flagged = find_unsupported_numbers(report, evidence)
    if not flagged:
        return {"unverified_claims": [], "revised_sentences": 0}

    revised = _model("report_model", s).invoke(
        REVISE_PROMPT.format(
            flagged="\n".join(
                f"- {f['sentence']}  (확인 안 된 수치: "
                + ", ".join(f"{t} → {REASON_KO[r]}" for t, r in zip(f["numbers"], f["reasons"]))
                + ")"
                for f in flagged
            ),
            report=report,
            results=_format_results(selected),
        )
    ).content.strip()
    # 고친 결과가 비었거나 지나치게 짧아지면(구조가 깨짐) 원래 보고서를 유지
    if len(revised) < len(report) * 0.5:
        revised = report
    remaining = find_unsupported_numbers(revised, evidence)
    return {
        "report": revised,
        "unverified_claims": [f["sentence"] for f in remaining],
        "revised_sentences": len(flagged),
    }
