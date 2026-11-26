# 품질 평가 (eval)

질문 10개로 에이전트를 실행해 보고서 품질을 수치로 비교합니다.

## 실행
```powershell
uv run python -m eval.run_eval --limit 2 --no-judge     # 먼저 작게 시험 (LLM 심판 끔)
uv run python -m eval.run_eval                          # 10문항 × no_plan, baseline, improved
uv run python -m eval.run_eval --repeat 3               # 3회 반복 → 평균 ± 표준편차
uv run python -m eval.run_eval --variants improved mini_eval
uv run python -m eval.run_eval --langsmith              # LangSmith에도 기록 (.env에 LANGSMITH_API_KEY)
```
결과는 `eval/results/<시각>.md`(비교표)와 `.json`(원자료)으로 저장돼요.

## 데이터셋 (`dataset.json`)
질문마다 정답 대신 **"보고서가 꼭 다뤄야 할 관점"**(3~5개)을 적어 두었어요.
정답 수치는 시간이 지나면 바뀌지만, 다뤄야 할 관점은 잘 바뀌지 않기 때문이에요.
- 여러 갈래 질문 8개 (예: AI 규제 현황·시행 시기·기업 영향)
- 단순 질문 2개 (재검색이 필요 없는 경우도 확인)

## 지표 (`evaluators.py`)
| 지표 | 방식 | 의미 |
|---|---|---|
| 관점 커버율 `aspect_coverage` | LLM 심판 | 데이터셋의 관점을 구체적으로 다룬 비율 |
| 근거 일치율 `groundedness` | LLM 심판 | 구체적 주장(최대 12개)이 근거 자료와 맞는 정도. supported 1 / partial 0.5 / unsupported 0, 출처 없는 주장은 unsupported (환각 점검) |
| 수치 근거율 `numeric_grounding` | 규칙 | 수치가 들어간 문장 중 그 수치가 근거 자료에 실제로 있는 비율 (비용 없는 환각 점검) |
| 인용 번호 유효율 `citation_validity` | 규칙 | 보고서의 [번호]가 실제 출처 목록에 있는 비율 |
| 인용 포함 문장 비율 `citation_coverage` | 규칙 | 주장이 담긴 줄 중 출처가 붙은 줄의 비율 |
| 하위 질문 근거 확보율 `subq_coverage` | 에이전트 자체 판단 | 마지막 평가에서 ✓인 하위 질문 비율 |
| 출처 다양성 `source_diversity` | 규칙 | 서로 다른 도메인 수 (6개 이상 = 1점) |
| 검색 횟수 · 라운드 · 소요 시간 · 고친 문장 수 | 측정 | 비용과 속도, 수치 검사가 고친 문장 수 |

LLM 심판 모델은 `.env`의 `JUDGE_MODEL`(기본 `gpt-4o`)로 바꿀 수 있어요.

## 비교 설정 (`variants.py`)
| 이름 | 설정 |
|---|---|
| `no_plan` | 질문 분해 없음(`use_plan=False`), 한 번 검색 후 요약 → 처음 버전에 가까움 |
| `baseline` | 질문 분해 + 병렬 검색, 재검색 없음(`max_loops=1`), 규칙 점검 끔, 평가 gpt-4o-mini |
| `improved` | 현재 기본값 (재검색 최대 3회 + 규칙 점검 + 평가 gpt-4o) |
| `no_verify` | improved에서 보고서 수치 검사(`verify_report`)만 끔 → 수치 검사의 효과 측정용 |
| `mini_eval` | improved에서 평가 모델만 gpt-4o-mini (비용 절감안) |

설정은 그래프에 `config["configurable"]`로 전달되므로 코드를 바꾸지 않고 비교할 수 있어요.

기본 비교 대상은 `no_plan`, `baseline`, `improved`예요.
- `no_plan → baseline`: 질문 분해의 효과
- `baseline → improved`: 재검색·규칙 점검의 효과
- `no_verify → improved`: 수치 검사의 효과 (`--variants no_verify improved`로 따로 실행)

## 비용 참고
1회 실행(10문항 × 3설정)에 Tavily 검색 약 100~130회, OpenAI 호출 약 150~250회가 일어나요.
`--repeat 3`이면 그 3배예요. Tavily 무료 한도(월 1,000회)를 생각해 처음에는 `--limit 2`로 시험해 보세요.

## 결과 해석 팁
- `--repeat`를 쓰면 표에 "평균 ± 표준편차"가 나와요. 두 설정의 차이가 표준편차보다 작으면 우연일 가능성이 커요.
- `baseline` 대비 `improved`의 **관점 커버율·근거 일치율**이 오르고, 검색 횟수·시간이 얼마나 늘었는지를 함께 보세요.
- `mini_eval`이 `improved`와 품질 차이가 작다면 평가 모델을 mini로 바꿔 비용을 줄일 수 있다는 근거가 돼요.
- LLM 심판도 틀릴 수 있어요. 점수가 낮은 항목은 결과 파일의 "심판 코멘트"와 보고서를 직접 확인하세요.
