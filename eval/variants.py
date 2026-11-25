"""비교할 실행 설정. config["configurable"]로 그래프에 전달된다."""

VARIANTS: dict[str, dict] = {
    # 처음 버전에 가까운 조건: 질문을 쪼개지 않고 한 번 검색 후 요약
    "no_plan": {"use_plan": False, "max_loops": 1, "eval_model": "gpt-4o-mini", "min_domains": 0, "min_results_per_subq": 0},
    # 질문 분해 + 병렬 검색까지만: 재검색·규칙 점검 없음, 평가 gpt-4o-mini
    "baseline": {"max_loops": 1, "eval_model": "gpt-4o-mini", "min_domains": 0, "min_results_per_subq": 0},
    # 현재 기본 설정 (.env 값)
    "improved": {},
    # 비용 절감안: 나머지는 그대로, 평가 모델만 mini
    "mini_eval": {"eval_model": "gpt-4o-mini"},
}

DESCRIPTIONS = {
    "no_plan": "질문 분해 없음, 한 번 검색 후 요약 (처음 버전에 가까움)",
    "baseline": "질문 분해 + 병렬 검색, 재검색·규칙 점검 없음 (평가 gpt-4o-mini)",
    "improved": "현재 기본 설정 (질문 분해 + 재검색 최대 3회 + 규칙 점검 + 평가 gpt-4o)",
    "mini_eval": "improved와 같지만 평가 모델만 gpt-4o-mini",
}

# 기본으로 비교할 설정
DEFAULT_VARIANTS = ["no_plan", "baseline", "improved"]
