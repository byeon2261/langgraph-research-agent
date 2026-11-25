# LangGraph 리서치 에이전트

질문 → **하위 질문으로 분해(plan)** → **사용자 확인(interrupt)** → 하위 질문별 **병렬 검색(Send)** → **엄격한 평가(강한 모델 + 규칙 점검)** → 부족한 항목만 재검색 (최대 3라운드) → **보고서 스트리밍** · 같은 대화에서 **후속 질문** 가능(체크포인터)

```
START → plan → review_plan ─┬─ search ─┐       (review=true면 여기서 멈추고 사용자 승인/수정)
                            ├─ search ─┼→ evaluate ─┬→ write_report → END
                            └─ search ─┘            └→ generate_query ─┬─ search ─┐
                                                                       └─ search ─┴→ evaluate …
```

## 핵심 결과
10문항 × 3회 평가 결과 (자세한 내용은 아래 "평가 결과 2", 원본은 [`eval/results/20261125-1655.md`](eval/results/20261125-1655.md))

| | 질문 분해 없음 | 질문 분해 | 질문 분해 + 재검색 |
|---|---|---|---|
| 근거 일치율 | 0.88 | **0.94** | 0.93 |
| 관점 커버율 | 0.91 | 0.91 | **0.94** |
| 출처 도메인 다양성 | 0.50 | **1.00** | **1.00** |
| 평균 소요 시간 | 11.6초 | 19.8초 | 22.3초 |

- 질문을 하위 질문으로 나눠 병렬 검색하면 근거 없는 주장이 줄고 출처가 다양해진다
- 평가를 돌려 **재검색 결과가 보고서에 반영되지 않던 버그**를 발견 → 수정 후 관점 커버율 0.84 → 0.94

## 구조
```
research_agent/
  state.py    # State + SearchState(Send로 넘기는 개별 검색 입력)
  prompts.py  # plan / 추가 검색어 / 평가 / 보고서 프롬프트 (오늘 날짜 포함)
  nodes.py    # 노드 6개: plan, review_plan, generate_query, search, evaluate, write_report
  graph.py    # build_graph(checkpointer) + Studio/서버용 graph
main.py       # CLI (SQLite 체크포인터, 계획 승인, 후속 질문, 토큰 스트리밍)
tests/        # 백엔드 테스트 (가짜 LLM/검색, API 키 불필요)
eval/         # 품질 평가: 데이터셋 10문항, 지표, 설정 비교 스크립트
.github/workflows/ci.yml  # push 때 백엔드·프런트엔드 테스트 자동 실행
frontend/     # React 웹 화면
langgraph.json  # LangGraph Studio용 설정
```

## 설정 (.env)
| 변수 | 기본값 | 설명 |
|---|---|---|
| `OPENAI_MODEL` | gpt-4o-mini | 계획, 검색어 생성 모델 |
| `EVAL_MODEL` | gpt-4o | 평가 전용 모델 (엄격한 판단용) |
| `REPORT_MODEL` | `OPENAI_MODEL`과 같음 | 보고서 작성 모델 |
| `SEARCH_MAX_RESULTS` | 3 | 검색어 1개당 가져올 결과 수 |
| `MIN_DOMAINS` | 3 | 전체 출처의 최소 도메인 수 |
| `MIN_RESULTS_PER_SUBQ` | 2 | 하위 질문 1개당 최소 검색 결과 수 |
| `MAX_LOOPS` | 3 | 최대 검색 라운드 수 |
| `MAX_CONTENT_CHARS` | 800 | 검색 결과 1건의 본문 최대 글자 수 (토큰 관리) |
| `MAX_RESULTS_PER_SUBQ_IN_PROMPT` | 6 | 하위 질문당 평가/보고서 프롬프트에 넣을 최대 결과 수 (넘치면 최근 재검색 결과 우선) |
| `SEARCH_RETRIES` | 2 | 검색 실패 시 재시도 횟수 |
| `JUDGE_MODEL` | gpt-4o | 품질 평가의 LLM 심판 모델 |

설정은 실행할 때 `config["configurable"]`로 덮어쓸 수도 있어요. 예) `graph.invoke(inputs, {"configurable": {"max_loops": 1}})`

그래프 입력값 `review`(true/false)로 검색 전 계획 확인 여부를 정해요. Studio에서는 Input에 `"review": true`를 넣으면 돼요.

## 실행 (uv)
```powershell
cd C:\langgraph-research-agent
uv sync                      # .venv 생성 + 의존성 설치
copy .env.example .env       # 그다음 .env에 API 키 입력
uv run main.py "LangGraph 최신 기능은?"
```

### CLI 사용법
```powershell
uv run main.py                     # 대화형: 질문 → 계획 확인 → 보고서 → 후속 질문 반복
uv run main.py --auto "질문"       # 계획 확인 건너뛰기
uv run main.py --thread 1a2b3c4d   # 이전 대화 이어 가기 (thread id는 시작할 때 출력됨)
```
계획 확인 단계 입력: `Enter` 승인 · `2 새 문장` 수정 · `-3` 삭제 · `+새 문장` 추가 (여러 개는 `;`로 구분)

## 테스트
```powershell
uv run pytest                       # 백엔드 50개 (약 1초, API 키 불필요)
cd frontend; npm test               # 프런트엔드 9개 (Vitest)
```
| 파일 | 확인하는 것 |
|---|---|
| `tests/test_nodes.py` | 설정 덮어쓰기, 출처 정렬·중복 제거, 규칙 점검, 재검색 번호 연결, interrupt 응답 처리, 검색 재시도, 라우팅 |
| `tests/test_graph.py` | 전체 흐름, 병렬 검색 수, `max_loops`, interrupt → 재개 → 후속 질문, 검색 실패, 토큰 스트리밍 |
| `tests/test_cli.py` | CLI 계획 확인 입력 파서 |
| `tests/test_eval.py` | 평가 지표 계산, 평가 스크립트 전체 실행 |
| `frontend/src/lib/turns.test.js` | 출처 링크 변환, 화면 상태 갱신, 진행 단계 문구 |

GitHub에 push하면 `.github/workflows/ci.yml`이 같은 테스트를 자동으로 돌려요.

## 품질 평가
```powershell
uv run python -m eval.run_eval --limit 2 --no-judge   # 작게 시험
uv run python -m eval.run_eval --repeat 3             # no_plan vs baseline vs improved, 10문항 × 3회
```
질문 10개와 "꼭 다뤄야 할 관점"으로 관점 커버율, 근거 일치율(LLM 심판), 인용 유효율 등을 측정해 설정별로 비교해요. 자세한 내용은 [`eval/README.md`](eval/README.md) 참고.

## Studio로 그래프 보기
```powershell
.\dev.ps1
```
`dev.ps1`은 UTF-8 모드를 켠 뒤 `uv run langgraph dev`를 실행해요. (아래 트러블슈팅 3번 참고)


## 웹 화면 (React)
```powershell
.\dev.ps1                 # 터미널 1: 백엔드
cd frontend; npm install; npm run dev   # 터미널 2: 프런트엔드
```
http://localhost:5173 접속. 자세한 내용은 `frontend/README.md` 참고.

## 개선 이력: "복잡한 질문도 검색 1회로 끝나는" 문제

### 문제
"국내외 AI 규제 법안 현황과 시행 시기, 기업에 미치는 영향"처럼 여러 갈래인 질문도 검색 1회 만에 `is_sufficient=True`가 나와 재검색 루프가 의미가 없었음.

### 원인
- 평가를 `gpt-4o-mini`가 스스로 하면서 항목을 너그럽게 통과시킴
- 검색어 1개로 모든 갈래를 찾으려 해서, 일부 항목은 근거가 얇은 채로 보고서가 작성됨
- 평가 근거가 State에 남지 않아 왜 통과됐는지 확인할 수 없었음

### 해결 (4가지)
1. **질문 분해 + 병렬 검색 (Plan-and-Execute)**
   - `plan` 노드가 질문을 하위 질문 3~4개와 검색어로 나눔
   - `Send`로 하위 질문마다 `search`를 병렬 실행하고, 모두 끝나면 `evaluate`가 한 번 실행됨(fan-in)
   - 재검색 때는 근거가 없는 하위 질문만 새 검색어를 만듦
2. **평가 전용 강한 모델**: `evaluate`만 `EVAL_MODEL`(기본 `gpt-4o`) 사용. 애매하면 false로 판단하도록 프롬프트 강화
3. **규칙 기반 점검**: LLM 판단과 별개로 출처 도메인 수(`MIN_DOMAINS`)와 하위 질문별 결과 수(`MIN_RESULTS_PER_SUBQ`)를 확인. 기준 미달이면 LLM이 통과시켜도 재검색
4. **평가 근거 기록**: `covered`(하위 질문별 ✓/✗)와 `rule_notes`(규칙 점검 결과)를 State에 저장 → Studio, CLI, 웹 화면에서 확인 가능

### 조절 팁
- 재검색이 너무 많으면: `MIN_DOMAINS=2`, `MIN_RESULTS_PER_SUBQ=1`로 완화
- 비용을 줄이려면: `EVAL_MODEL=gpt-4o-mini` (대신 평가가 다시 너그러워질 수 있음)

## 개선 이력 2: 안정성 보완 + 학습 확장

### 결과 품질·안정성
1. **출처 번호 불일치 수정**
   - 문제: 병렬 검색이라 결과 도착 순서가 매번 달라, 보고서의 `[3]`과 웹 화면 출처 3번이 다를 수 있었음
   - 해결: `_select()`가 결과를 "하위 질문 순서 → 수집 순서"로 정렬·중복 제거해 번호를 고정하고, `write_report`가 같은 순서의 `sources`(번호 포함)를 함께 반환. 웹 화면은 이 목록으로 출처 패널을 그리고 `[번호]`를 해당 URL 링크로 바꿈
2. **오늘 날짜 주입**: 모든 프롬프트에 `{today}`를 넣어 "최신/현재" 질문이 과거 연도로 검색되지 않게 함. 평가도 오래된 자료만 있으면 false
3. **토큰 관리**: 검색 결과 본문을 `MAX_CONTENT_CHARS`로 자르고, 프롬프트에는 하위 질문당 `MAX_RESULTS_PER_SUBQ_IN_PROMPT`건만 넣음. 후속 질문 때는 이번 하위 질문의 결과만 사용
4. **오류 처리**
   - OpenAI: `max_retries=3`, `timeout=60`
   - 노드 단위 재시도: `RetryPolicy(max_attempts=2)` (구조화 출력 파싱 실패 등)
   - Tavily: 실패 시 `SEARCH_RETRIES`만큼 재시도, 끝내 실패하면 그래프를 멈추지 않고 `search_errors`에 기록 → 평가에서 부족으로 판정되어 재검색
   - 재검색 검색어를 하위 질문 **번호**로 연결해, LLM이 문장을 바꿔 써도 결과가 올바른 하위 질문에 묶이게 함

### LangGraph 학습 확장
5. **체크포인터 (대화 이어 가기)**
   - CLI: `SqliteSaver`(`checkpoints.sqlite`)로 프로그램을 껐다 켜도 `--thread`로 이어 감
   - 서버(`langgraph dev`): 서버가 체크포인터를 자동으로 붙여 줌 → 그래서 `graph.py`의 `graph`에는 체크포인터를 넣지 않음
   - 같은 thread에서 새 질문을 넣으면 `past_questions`와 이전 보고서를 plan 프롬프트에 넣어 "그 부분 더 자세히" 같은 후속 질문을 이해함
   - 웹 화면: 세션 목록을 브라우저(localStorage)에 저장해 새로고침해도 기록 유지
6. **`interrupt` (사람 개입)**
   - `review_plan` 노드가 `interrupt()`로 멈추고 하위 질문을 보여 줌
   - `Command(resume={"sub_questions": [...]})`로 재개. 수정 안 한 항목은 원래 검색어, 새로 쓴 항목은 문장 그대로 검색
   - interrupt 노드는 재개 시 처음부터 다시 실행되므로 interrupt 앞에 부작용(외부 호출)을 두지 않음
7. **보고서 실시간 스트리밍**: `stream_mode=["updates", "messages"]`로 노드 진행과 LLM 토큰을 함께 받고, `langgraph_node == "write_report"`인 토큰만 화면에 출력

## 개선 이력 3: 테스트와 품질 평가
- **설정을 실행 시점에 주입**: 모듈 상수였던 설정을 `Settings` + `config["configurable"]`로 바꿔, 같은 코드로 여러 설정을 비교할 수 있게 함
- **테스트 확대**: 4개 → 백엔드 43개 (이후 50개) + 프런트엔드 9개. 화면 상태 로직은 `frontend/src/lib/turns.js`로 분리해 React 없이 테스트
- **CI**: GitHub Actions로 push마다 테스트와 빌드 확인
- **품질 평가**: 10문항 데이터셋, 규칙·LLM 심판 지표 7종, 설정 비교(`baseline`/`improved`/`mini_eval`), 로컬 또는 LangSmith 실행

## 평가 결과 (2026-11-25, 10문항 × 2설정, 1회 실행)
원본: [`eval/results/20261125-1515.md`](eval/results/20261125-1515.md)

| 지표 | baseline | improved | 차이 |
|---|---|---|---|
| 관점 커버율 (LLM 심판) | **0.90** | 0.84 | -0.06 |
| 근거 일치율 (LLM 심판) | **1.00** | 0.97 | -0.03 |
| 인용 번호 유효율 | 1.00 | 1.00 | 0 |
| 인용 포함 문장 비율 | 0.73 | **0.75** | +0.02 |
| 하위 질문 근거 확보율 | 0.95 | 0.88 | (평가 모델이 달라 직접 비교 불가) |
| 출처 다양성 | 1.00 | 1.00 | 0 |
| 검색 횟수 | 4 | 6.2 | +55% |
| 소요 시간(초) | 17.2 | 21.4 | +24% |

- `baseline`: 재검색·규칙 점검 없음, 평가 gpt-4o-mini
- `improved`: 재검색 최대 3회 + 규칙 점검 + 평가 gpt-4o

### 결론: 재검색 루프는 아직 품질을 높이지 못했다
`improved`는 검색을 55% 더 하고 24% 더 오래 걸렸지만, 품질 지표는 같거나 조금 낮았다.

### 원인 분석
1. **재검색 결과가 보고서에 거의 들어가지 않는 버그 (가장 유력)**
   - 첫 검색에서 하위 질문당 결과 3건(`SEARCH_MAX_RESULTS=3`)이 들어오는데, 프롬프트에는 하위 질문당 최대 4건(`MAX_RESULTS_PER_SUBQ_IN_PROMPT=4`)만 **도착 순서대로** 넣는다.
   - 그래서 1차 재검색 결과는 1건만, 2차 재검색 결과는 0건이 평가·보고서에 반영된다. 재검색을 해도 평가가 같은 자료를 다시 보게 되어 계속 "부족"이 나오고, 검색 횟수만 늘어난다.
   - 이것은 앞선 개선(토큰 관리 3번)이 재검색 루프와 충돌해서 생긴 문제로, 평가를 돌려서 처음 발견했다.
2. **baseline이 이미 강함**: 두 설정 모두 질문 분해(plan)와 하위 질문별 병렬 검색을 쓴다. 이번 평가는 "재검색·규칙 점검"만의 효과를 본 것이고, 가장 큰 개선이었던 질문 분해의 효과는 측정되지 않았다.
3. **한 문항의 영향이 큼**: `korea-ai-startup-investment`에서 improved가 0.25(baseline 1.00)로, 관점 커버율 평균 차이(-0.06)의 대부분이 이 문항에서 나왔다. 반대로 `semiconductor-export`는 improved가 더 좋았다(1.00 vs 0.50).
4. **표본이 작음**: 10문항 1회 실행이고, LLM 출력과 검색 결과는 실행마다 달라진다. 0.06 차이는 우연일 수 있다.
5. **지표 한계**: 근거 일치율과 인용 번호 유효율은 두 설정 모두 1.00 근처라 차이를 가려내지 못한다(천장 효과). "하위 질문 근거 확보율"은 baseline은 gpt-4o-mini, improved는 gpt-4o가 스스로 매긴 값이라 비교 지표로 쓰면 안 된다.

### 개선 계획 → 개선 이력 4에서 반영
1. `_select()`가 재검색 결과를 우선 포함하도록 수정 ✅
2. 같은 평가를 3회 반복해 평균과 편차 확인 (`--repeat`) ✅
3. 질문 분해가 없는 `no_plan` 설정 추가 ✅
4. 근거 일치율 심판을 더 엄격하게 ✅

> 원자료 확인: `korea-ai-startup-investment`의 improved 보고서는 3라운드를 재검색하고도 "주요 투자사: 검색 결과로 확인되지 않음"이라고 썼다. 재검색 결과가 보고서 프롬프트에 들어가지 못했다는 위 분석과 일치한다.

## 개선 이력 4: 평가에서 찾은 버그 수정과 평가 방법 보강
1. **재검색 결과 누락 버그 수정**
   - 검색 결과마다 `round`(몇 번째 검색 라운드)와 `turn`(몇 번째 질문)을 기록
   - `_select()`는 하위 질문당 상한을 넘으면 **최근 라운드 결과를 우선** 남기고, 출력은 라운드 순서로 정렬해 번호가 항상 같게 유지
   - 상한 기본값 4 → 6 (첫 검색 3건 + 재검색 3건이 모두 들어가도록)
   - 후속 질문 때 이전 질문의 결과가 섞이지 않도록 `turn`으로도 걸러냄
   - 회귀 테스트 추가: `test_select_keeps_retry_results_when_capped`, `test_retry_results_reach_report`
2. **반복 평가**: `--repeat N`으로 같은 문항을 N회 돌려 "평균 ± 회차 간 표준편차"를 표에 표시. 차이가 표준편차보다 작으면 우연일 수 있다고 판단
3. **`no_plan` 설정**: `use_plan=False`로 질문을 쪼개지 않고 원래 질문으로 한 번 검색 → 질문 분해의 효과를 따로 측정
4. **더 엄격한 근거 일치율 심판**: 주장을 최대 12개까지, 출처 없는 구체적 주장도 포함, `supported`(1점) / `partial`(0.5점) / `unsupported`(0점) 3단계로 채점

다음 평가에서는 `no_plan → baseline` 차이로 **질문 분해**의 효과를, `baseline → improved` 차이로 **재검색·규칙 점검**의 효과를 본다.

### 시험 실행 (2026-11-25 16:24, 2문항 × 3설정, 1회, LLM 심판 끔)
원본: [`eval/results/20261125-1624.md`](eval/results/20261125-1624.md) · 명령: `uv run python -m eval.run_eval --limit 2 --no-judge`

| 지표 | no_plan | baseline | improved |
|---|---|---|---|
| 인용 번호 유효율 | 1.00 | 1.00 | 1.00 |
| 인용 포함 문장 비율 | 0.63 | **0.74** | 0.51 |
| 출처 다양성 | 0.50 | **1.00** | **1.00** |
| 검색 횟수 | 1 | 4 | 4 |
| 검색 라운드 | 1 | 1 | 1 |
| 소요 시간(초) | 15.4 | 18.9 | 18.7 |

**목적**: 개선 이력 4의 수정 후, 새 설정(`no_plan`)과 평가 스크립트가 실제 API로 끝까지 도는지 확인. 품질 비교용 실행이 아니다.

**확인한 것**
- 3개 설정 모두 오류 없이 실행되고, `no_plan`은 의도대로 검색 1회로 끝남
- 질문 분해(`no_plan → baseline`)로 출처 도메인이 2배 다양해짐 (0.50 → 1.00). 2문항뿐이라 참고 수치

**이 결과로 판단할 수 없는 것**
- **재검색 버그 수정의 효과**: 두 문항 모두 `improved`가 1라운드 만에 충분하다고 판정해 재검색이 일어나지 않았다. 이번 실행에서 `improved`와 `baseline`은 사실상 같은 경로로 동작했다.
- **인용 포함 문장 비율 0.74 vs 0.51**: 위처럼 두 설정이 같은 경로였는데도 0.23이나 차이가 났다. 이는 설정 차이가 아니라 **같은 조건에서도 실행마다 생기는 편차**로 보는 게 맞다. → 설정 간 비교는 `--repeat 3`으로 편차를 함께 봐야 한다는 근거
- 관점 커버율·근거 일치율: 심판을 꺼서 측정하지 않음

**다음**: `uv run python -m eval.run_eval --repeat 3` (10문항, 심판 켬)으로 본 평가

## 평가 결과 2 (2026-11-25 16:55, 10문항 × 3설정 × 3회, 버그 수정 후)
원본: [`eval/results/20261125-1655.md`](eval/results/20261125-1655.md) · 명령: `uv run python -m eval.run_eval --repeat 3`

| 지표 | no_plan | baseline | improved |
|---|---|---|---|
| 관점 커버율 (LLM 심판) | 0.91 ± 0.01 | 0.91 ± 0.04 | **0.94 ± 0.01** |
| 근거 일치율 (LLM 심판, 엄격 기준) | 0.88 ± 0.02 | **0.94 ± 0.02** | 0.93 ± 0.04 |
| 인용 번호 유효율 | 1.00 | 1.00 | 1.00 |
| 인용 포함 문장 비율 | 0.63 ± 0.05 | **0.67 ± 0.04** | 0.66 ± 0.07 |
| 출처 다양성 | 0.50 | **1.00** | **1.00** |
| 검색 횟수 | 1 | 4 | 6.0 |
| 소요 시간(초) | 11.6 ± 1.1 | 19.8 ± 0.5 | 22.3 ± 0.9 |

(± = 3회 실행의 회차별 평균 사이 표준편차. 하위 질문 근거 확보율은 설정마다 판단 모델이 달라 제외)

### 결론
1. **질문 분해가 가장 큰 효과** (`no_plan → baseline`)
   - 근거 일치율 0.88 → 0.94 (+0.06, 표준편차 0.02보다 큼), 출처 다양성 2배
   - `no_plan`의 낮은 점수는 대부분 근거 자료에 없는 일반론·수치였다 (예: `what-is-langgraph` 3회 모두 0.60). 검색 1회로 모은 자료가 부족하면 LLM이 빈 곳을 채운다
   - 대가: 소요 시간 +71% (11.6초 → 19.8초)
2. **재검색·규칙 점검은 작은 개선** (`baseline → improved`)
   - 관점 커버율 0.91 → 0.94 (+0.03). baseline의 편차(±0.04) 안이라 **확실한 개선이라고 말하기는 어렵다**
   - 근거 일치율은 차이 없음 (0.94 vs 0.93)
   - 대가: 검색 +51%, 시간 +12%
   - 30회 중 15회(5개 문항)에서 재검색이 일어났고, 그중 `what-is-langgraph`(근거 0.94→0.99), `youth-support`(관점 0.92→1.00), `battery-recycling`(근거 0.87→0.93)은 좋아졌다
3. **재검색 버그 수정 효과 확인** (첫 평가와 비교)
   | 관점 커버율 | 첫 평가 (15:15, 수정 전) | 이번 (16:55, 수정 후) |
   |---|---|---|
   | baseline | 0.90 | 0.91 |
   | improved | 0.84 | **0.94** |
   | `korea-ai-startup-investment` improved | 0.25 | **0.75** |
   - 재검색을 하지 않는 baseline은 그대로인데, 재검색을 하는 improved만 0.10 올랐다 → 버그 수정의 효과로 볼 수 있다
   - 관점 커버율 심판은 두 평가에서 같은 기준이라 비교 가능. 근거 일치율은 이번에 심판을 엄격하게 바꿔 **직접 비교하지 않는다**. 첫 평가는 1회 실행이라 편차를 모른다는 한계도 있다

### 남은 문제: 근거를 끝내 못 찾으면 근거 없는 수치가 들어간다
- `korea-ai-startup-investment`에서 improved는 3회 모두 3라운드까지 재검색했지만 하위 질문 근거 확보율 0.58, 근거 일치율 0.71로 가장 낮았다
- 심판은 "2026년 AI 스타트업 총 투자액 2,450억 원" 같은 수치를 근거 자료에 없다고 판정했다. 근거가 부족한 채로 최대 라운드에 도달하면, 보고서 단계에서 빈 곳을 채우는 것으로 보인다 (심판 오판일 수도 있어 원문 확인 필요)
- 개선 아이디어: 근거가 없는 하위 질문은 보고서 프롬프트에서 "이 항목은 수치를 쓰지 말 것"으로 명시하거나, 보고서 작성 후 인용 없는 수치를 검사하는 노드 추가

### 한 줄 요약
> 질문 분해로 근거 일치율 +0.06, 출처 다양성 2배를 얻었다. 재검색 루프는 평가에서 숨은 버그를 찾아 고친 뒤 관점 커버율이 0.84 → 0.94로 회복됐지만, baseline 대비 이득(+0.03)은 편차 수준이고 검색 비용은 51% 늘었다.

## 다음 단계
1. 근거를 못 찾은 하위 질문에서 근거 없는 수치가 나오는 문제 해결 (평가 결과 2 "남은 문제")
2. `mini_eval` 설정을 평가해, 평가 모델을 gpt-4o-mini로 바꿔도 품질이 유지되는지 확인 (비용 절감)
3. Docker로 배포하고 README에 스크린샷 추가
4. 하위 질문별 보고서 섹션 접기/펼치기

## 트러블슈팅 (Windows)

### 1. `.env` 읽을 때 `UnicodeDecodeError: 'cp949' codec can't decode ...`
- 원인: Windows 기본 인코딩(cp949)으로 UTF-8 한글 주석이 있는 `.env`를 읽음
- 해결: `.env`, `.env.example`에서 한글 주석 제거 → **`.env`에는 영문만 쓰기**

### 2. `SystemError: ConsoleRenderer with colors=True on Windows requires the colorama package`
- 원인: Studio 서버가 Windows에서 컬러 로그를 출력할 때 `colorama`가 필요함
- 해결: `pyproject.toml`의 `dev` 그룹에 `colorama` 추가 후 `uv sync`

### 3. 서버 시작 직후 `langgraph_api\validation.py` 에서 `UnicodeDecodeError: 'cp949'`
- 원인: langgraph_api가 내부 파일을 인코딩 지정 없이 읽어 cp949로 해석됨
- 해결: Python UTF-8 모드로 실행
  ```powershell
  $env:PYTHONUTF8=1      # 현재 터미널에만 적용
  uv run langgraph dev
  ```
  - 매번 입력하기 싫으면 `.\dev.ps1` 사용
  - 영구 적용: `setx PYTHONUTF8 1` 실행 후 터미널 재시작
- `.ps1` 실행이 막히면: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 4. 그 밖의 원인 모를 패키지 오류
- Python 3.14는 최신 버전이라 호환 문제가 생길 수 있음 → 3.12로 고정
  ```powershell
  uv python pin 3.12
  uv sync
  ```
