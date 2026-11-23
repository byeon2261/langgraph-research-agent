import operator
from typing import Annotated, TypedDict


class State(TypedDict):
    question: str
    # operator.add reducer: 노드가 반환한 리스트를 덮어쓰지 않고 이어 붙인다
    queries: Annotated[list[str], operator.add]
    results: Annotated[list[dict], operator.add]
    is_sufficient: bool
    missing_info: str
    loop_count: int
    report: str
