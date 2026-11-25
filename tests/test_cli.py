"""CLI의 계획 확인 입력 파서 테스트"""
import pytest

import main

PAYLOAD = {"message": "m", "sub_questions": ["A", "B", "C"], "queries": ["qa", "qb", "qc"]}


@pytest.mark.parametrize(
    "line,expected",
    [
        ("", True),
        ("2 새 B", {"sub_questions": ["A", "새 B", "C"]}),
        ("-1", {"sub_questions": ["B", "C"]}),
        ("+D", {"sub_questions": ["A", "B", "C", "D"]}),
        ("-3; +D; 1 새 A", {"sub_questions": ["새 A", "B", "D"]}),
        ("9 없는 번호", {"sub_questions": ["A", "B", "C"]}),
    ],
)
def test_ask_review(monkeypatch, capsys, line, expected):
    monkeypatch.setattr("builtins.input", lambda _: line)
    assert main.ask_review(PAYLOAD) == expected
