"""수치 해석·비교 규칙 테스트 (research_agent/numbers.py)"""
import pytest

from research_agent.numbers import check_sentence, extract_mentions, is_checkable, keywords


def one(text):
    ms = [m for m in extract_mentions(text) if is_checkable(m)]
    assert len(ms) == 1, ms
    return ms[0]


@pytest.mark.parametrize(
    "text,value,unit",
    [
        ("총 2,450억 원", 2450e8, "원"),
        ("1.2조 원", 1.2e12, "원"),
        ("1조 2,000억 원", 1.2e12, "원"),  # 큰 단위가 이어지면 합침
        ("2천억 원", 2e11, "원"),
        ("3만 명", 3e4, "명"),
        ("$3.8 billion", 3.8e9, "달러"),
        ("38억 달러", 3.8e9, "달러"),
        ("120 million users", 1.2e8, ""),
        ("70B 모델", 7e10, ""),
        ("35%", 35, "%"),
        ("35 percent", 35, "%"),
        ("2.5%p 상승", 2.5, "%p"),
        ("약700억 원", 700e8, "원"),  # 한글 바로 뒤의 숫자도 인식
    ],
)
def test_extract_value_and_unit(text, value, unit):
    m = one(text)
    assert m.value == pytest.approx(value) and m.unit == unit


@pytest.mark.parametrize(
    "text",
    ["2026년", "11월 25일", "1위", "3가지", "2분기", "목록 1. 2. 3.", "3개", "Llama 3.1", "gpt4o", "v1.2"],
)
def test_not_checkable(text):
    assert [m for m in extract_mentions(text) if is_checkable(m)] == []


@pytest.mark.parametrize(
    "claim,evidence,ok",
    [
        ("시장 규모는 1.2조 원이다", "국내 시장 규모 1조 2,000억 원", True),  # 표기가 달라도 같은 값
        ("시장 규모는 1.2조 원이다", "국내 시장 규모 1조 1,800억 원", True),  # 1.2조 = 1.15~1.25조 반올림 범위
        ("시장 규모는 1.2조 원이다", "국내 시장 규모 1조 원", False),
        ("시장 규모는 38억 달러다", "The market size reached $3.8 billion", True),  # 영어 자료
        ("성장률은 35%다", "성장률이 35.4%로 집계", True),  # 35% = 34.5~35.5
        ("성장률은 35.0%다", "성장률이 35.4%로 집계", False),  # 소수점까지 쓰면 더 엄격
        ("성장률은 35%다", "성장률 35개 기업", False),  # 단위가 다름
        ("투자액은 35억 원이다", "투자액 35억", True),  # 근거에서 단위 생략은 허용
        ("AI 스타트업 투자 성장률은 35%다", "AI 스타트업 투자는 35% 늘었다", True),  # 맥락 일치
        ("반도체 수출 증가율은 35%다", "AI 스타트업 투자는 35% 늘었다", False),  # 맥락 불일치
    ],
)
def test_check_sentence(claim, evidence, ok):
    n_claims, issues = check_sentence(claim, [evidence])
    assert n_claims == 1 and (issues == []) == ok


def test_issue_reasons():
    assert check_sentence("규모는 50억 원이다", ["규모 40억 원"])[1][0].reason == "not_found"
    assert check_sentence("규모는 50억 달러다", ["규모 50억 원"])[1][0].reason == "unit_mismatch"
    assert check_sentence("반도체 규모는 50억 원이다", ["스타트업 투자 50억 원"])[1][0].reason == "context_mismatch"


def test_keywords_strip_particles_and_stopwords():
    assert {"투자액", "스타트업"} <= keywords("스타트업의 투자액은 전년 대비 증가")
    assert "대비" not in keywords("전년 대비")
