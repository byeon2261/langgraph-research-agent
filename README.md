# LangGraph 리서치 에이전트

질문 → **하위 질문으로 분해(plan)** → **사용자 확인(interrupt)** → 하위 질문별 **병렬 검색(Send)** → **엄격한 평가(강한 모델 + 규칙 점검)** → 부족한 항목만 재검색 (최대 3라운드) → **보고서 스트리밍** · 같은 대화에서 **후속 질문** 가능(체크포인터)

```
START → plan → review_plan ─┬─ search ─┐       (review=true면 여기서 멈추고 사용자 승인/수정)
                            ├─ search ─┼→ evaluate ─┬→ write_report → END
                            └─ search ─┘            └→ generate_query ─┬─ search ─┐
                                                                       └─ search ─┴→ evaluate …
```

## 구조
```
research_agent/
  state.py    # State + SearchState(Send로 넘기는 개별 검색 입력)
  prompts.py  # plan / 추가 검색어 / 평가 / 보고서 프롬프트 (오늘 날짜 포함)
  nodes.py    # 노드 6개: plan, review_plan, generate_query, search, evaluate, write_report
  graph.py    # build_graph(checkpointer) + Studio/서버용 graph
main.py       # CLI (SQLite 체크포인터, 계획 승인, 후속 질문, 토큰 스트리밍)
tests/        # 가짜 LLM/검색으로 그래프 흐름 검증 (API 키 불필요)
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
| `MAX_RESULTS_PER_SUBQ_IN_PROMPT` | 4 | 하위 질문당 평가/보고서 프롬프트에 넣을 최대 결과 수 |
| `SEARCH_RETRIES` | 2 | 검색 실패 시 재시도 횟수 |

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

### 테스트
```powershell
uv run pytest
```

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

## 다음 단계
1. LangSmith로 평가 데이터셋(질문 10개)을 만들어 개선 전후 출처 정확도·항목 커버율 비교
2. Docker로 배포하고 README에 스크린샷 추가
3. 하위 질문별 보고서 섹션 접기/펼치기

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
