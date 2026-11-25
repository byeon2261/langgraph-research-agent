import operator
from typing import Annotated, TypedDict


class State(TypedDict, total=False):
    question: str
    # 입력 옵션: True면 plan 직후 interrupt로 사용자 승인/수정을 받는다
    review: bool
    # 후속 질문 맥락: 같은 thread에서 이전에 했던 질문들 (체크포인터로 유지)
    past_questions: Annotated[list[str], operator.add]
    # 질문을 쪼갠 하위 질문
    sub_questions: list[str]
    # 이번 라운드에 병렬로 검색할 작업 [{query, sub_question}] (매 라운드 덮어씀)
    pending_queries: list[dict]
    # operator.add reducer: 병렬 검색 결과가 덮어써지지 않고 이어 붙는다
    queries: Annotated[list[str], operator.add]
    results: Annotated[list[dict], operator.add]
    search_errors: Annotated[list[str], operator.add]
    # 평가 근거
    covered: list[bool]
    rule_notes: list[str]
    is_sufficient: bool
    missing_info: str
    loop_count: int
    # 보고서와, 보고서의 [번호]와 똑같은 순서의 출처 목록
    report: str
    sources: list[dict]


class SearchState(TypedDict):
    """Send로 search 노드에 하나씩 넘기는 개별 작업 입력"""
    query: str
    sub_question: str
