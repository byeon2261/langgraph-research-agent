"""보고서 수치 검사기.

보고서 문장의 수치를 (값, 단위)로 해석하고, 근거 자료에 같은 값·같은 단위·관련 맥락의
수치가 있는지 확인한다.

- 한국어 크기 단위:  1.2조, 1조 2,000억, 2천억, 260억 원, 3만 명
- 영어 크기 단위:    $3.8 billion, 3.8B, 120 million, 35 percent
- 반올림 허용:       보고서에 적힌 마지막 자릿수의 절반 (35% → 34.5~35.5, 1.2조 → 1.15~1.25조)
- 맥락 확인:         근거 자료에서 그 수치 주변 문장과 보고서 문장에 공통 단어가 있어야 함
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------- 수치 해석 ----------
_BIG = {"조": 1e12, "억": 1e8, "만": 1e4}
_SMALL = {"천": 1e3, "백": 1e2}
_EN_MAG = {
    "trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3,
    "tn": 1e12, "bn": 1e9, "mn": 1e6, "T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3, "k": 1e3,
}
_CURRENCY = {"원": "원", "달러": "달러", "$": "달러", "usd": "달러", "엔": "엔", "유로": "유로", "€": "유로", "위안": "위안", "₩": "원"}
_PCT = {"%": "%", "퍼센트": "%", "percent": "%", "%p": "%p", "%포인트": "%p", "포인트": "%p"}
_COUNT = {"개": "개", "곳": "개", "건": "건", "명": "명", "개사": "개", "배": "배", "대": "대"}
# 검사하지 않는 단위 (날짜·순서·시간)
_SKIP_UNITS = {"년", "월", "일", "분기", "위", "차", "시", "분", "초", "주", "세", "회", "번째", "가지", "단계"}

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_TERM = re.compile(
    rf"(?P<cur>[$€₩])?\s?(?P<num>{_NUM})\s?(?P<small>[천백])?(?P<big>[조억만])?"
    r"(?:\s?(?P<en>trillion|billion|million|thousand|tn|bn|mn|[TBMKk])(?![A-Za-z]))?"
)
_UNIT = re.compile(
    r"\s?(%p|%포인트|%|퍼센트|percent|포인트|원|달러|usd|엔|유로|위안|개사|개|곳|건|명|배|대|"
    r"년|월|일|분기|위|차|시|분|초|주|세|회|번째|가지|단계)",
    re.IGNORECASE,
)


@dataclass
class Mention:
    value: float
    unit: str  # "%", "%p", "원", "달러", "개", "명", ..., "" (단위 없음)
    tol: float  # 반올림 허용 범위 (절대값)
    text: str  # 원문 표기 (예: "1조 2,000억 원")
    start: int
    end: int
    has_magnitude: bool


def _decimals(num: str) -> int:
    return len(num.split(".")[1]) if "." in num else 0


def _term_value(m: re.Match) -> tuple[float, float, bool]:
    num = m.group("num")
    v = float(num.replace(",", ""))
    mag = 1.0
    if m.group("small"):
        mag *= _SMALL[m.group("small")]
    if m.group("big"):
        mag *= _BIG[m.group("big")]
    if m.group("en"):
        mag *= _EN_MAG.get(m.group("en"), _EN_MAG.get(m.group("en").lower(), 1.0))
    tol = 0.5 * 10 ** (-_decimals(num)) * mag
    has_mag = mag > 1.0
    return v * mag, tol, has_mag


def extract_mentions(text: str) -> list[Mention]:
    """문장(또는 근거 자료)에서 수치 표현을 찾아 (값, 단위)로 해석한다.
    "1조 2,000억 원"처럼 큰 단위가 이어지면 하나의 값으로 합친다."""
    out: list[Mention] = []
    terms = [m for m in _TERM.finditer(text) if m.group("num")]
    i = 0
    while i < len(terms):
        m = terms[i]
        # 숫자 바로 앞이 숫자/소수점/영문자면 다른 토큰의 일부 (예: 버전 v1.2, 모델명 gpt4)
        if m.start("num") > 0 and re.match(r"[A-Za-z0-9.]", text[m.start("num") - 1]) and not m.group("cur"):
            i += 1
            continue
        value, tol, has_mag = _term_value(m)
        start, end = m.start(), m.end()
        last_big = _BIG.get(m.group("big") or "", 0)
        # 1조 2,000억처럼 더 작은 큰 단위가 이어지는 경우 합치기
        while i + 1 < len(terms) and last_big:
            nxt = terms[i + 1]
            gap = text[end:nxt.start()]
            nb = _BIG.get(nxt.group("big") or "", 0)
            if gap.strip() == "" and nb and nb < last_big:
                v2, tol, _ = _term_value(nxt)
                value += v2
                end, last_big = nxt.end(), nb
                i += 1
            else:
                break
        unit = ""
        if m.group("cur"):
            unit = _CURRENCY[m.group("cur")]
        um = _UNIT.match(text, end)
        if um:
            raw = um.group(1)
            key = raw.lower()
            unit = (
                _PCT.get(key) or _PCT.get(raw) or _CURRENCY.get(key) or _CURRENCY.get(raw)
                or _COUNT.get(raw) or raw
            )
            end = um.end()
        out.append(Mention(value, unit, tol, text[start:end].strip(), start, end, has_mag))
        i += 1
    return out


def is_checkable(m: Mention) -> bool:
    """검사 대상인지: 날짜·순서 단위, 연도, 단위 없는 작은 정수는 제외"""
    if m.unit in _SKIP_UNITS:
        return False
    if m.unit == "" and not m.has_magnitude:
        if 1900 <= m.value <= 2100 and float(m.value).is_integer():
            return False  # 연도
        if m.value <= 10:
            return False  # 목록 번호, "3가지" 같은 표현
    if m.unit in {"개", "건", "명", "대"} and m.value <= 10:
        return False
    return True


def _units_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    # 한쪽이 단위를 생략한 경우는 허용 (예: 근거 "투자액 2,450억", 보고서 "2,450억 원")
    return a == "" or b == ""


def values_match(claim: Mention, ev: Mention) -> bool:
    """보고서에 적힌 자릿수 기준으로만 반올림을 허용한다.
    근거가 "1조"인데 보고서가 "1.2조"라고 쓰면 근거보다 정밀한 값을 지어낸 것이므로 불일치"""
    return abs(claim.value - ev.value) <= claim.tol + abs(claim.value) * 1e-9


# ---------- 맥락 비교 ----------
_PARTICLES = (
    "으로는", "에서는", "에게서", "까지는", "부터는", "이라는", "에서", "으로", "까지", "부터", "에게",
    "보다", "처럼", "마다", "이며", "이고", "이다", "였다", "했다", "하는", "되는", "된", "한",
    "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만", "며",
)
_STOP = {
    "전년", "대비", "기준", "올해", "지난해", "현재", "최근", "이상", "이하", "가량", "규모", "수준",
    "기록", "기록했습니다", "증가", "감소", "성장", "달했", "있습니다", "것으로", "나타났", "예상",
    "전망", "따르면", "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
}
_WORD = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z\-]{2,}")


def _stem(w: str) -> str:
    if re.fullmatch(r"[가-힣]+", w):
        for p in _PARTICLES:
            if len(w) > len(p) + 1 and w.endswith(p):
                return w[: -len(p)]
    return w.lower()


def keywords(text: str) -> set[str]:
    words = {_stem(w) for w in _WORD.findall(text)}
    return {w for w in words if len(w) >= 2 and w not in _STOP}


def _has_hangul(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text))


def context_ok(sentence: str, evidence_text: str, ev: Mention, window: int = 120) -> bool:
    """근거 자료에서 수치 주변(앞 window자, 뒤 window/2자)에 보고서 문장과 같은 단어가 있는지.
    언어가 달라 비교할 수 없으면(한국어 보고서 vs 영어 자료) 통과로 본다."""
    around = evidence_text[max(0, ev.start - window): ev.end + window // 2]
    if not (_has_hangul(sentence) and _has_hangul(around)):
        return True  # 한국어 보고서 vs 영어 자료처럼 단어로 비교할 수 없으면 값·단위 일치만으로 인정
    return bool(keywords(sentence) & keywords(around))


# ---------- 문장 검사 ----------
@dataclass
class Issue:
    text: str  # 보고서의 수치 표기
    reason: str  # not_found / unit_mismatch / context_mismatch


REASON_KO = {
    "not_found": "근거 자료에 없는 값",
    "unit_mismatch": "근거 자료와 단위가 다름",
    "context_mismatch": "근거 자료에서 다른 대상에 대한 값",
}


def check_sentence(sentence: str, evidence_texts: list[str]) -> tuple[int, list[Issue]]:
    """(검사한 수치 개수, 문제 목록). evidence_texts: 이 문장이 근거로 삼을 자료 본문들"""
    claims = [m for m in extract_mentions(sentence) if is_checkable(m)]
    if not claims:
        return 0, []
    ev_mentions = [(t, m) for t in evidence_texts for m in extract_mentions(t)]
    issues = []
    for c in claims:
        same_value = [(t, m) for t, m in ev_mentions if values_match(c, m)]
        if not same_value:
            issues.append(Issue(c.text, "not_found"))
            continue
        same_unit = [(t, m) for t, m in same_value if _units_compatible(c.unit, m.unit)]
        if not same_unit:
            issues.append(Issue(c.text, "unit_mismatch"))
            continue
        if not any(context_ok(sentence, t, m) for t, m in same_unit):
            issues.append(Issue(c.text, "context_mismatch"))
    return len(claims), issues
