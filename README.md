# LangGraph 리서치 에이전트

질문 → 검색어 생성 → 웹 검색 → 충분성 평가 → (부족하면 재검색, 최대 3회) → 보고서 작성

## 구조
```
research_agent/
  state.py    # 그래프 State (reducer로 검색어/결과 누적)
  prompts.py  # 프롬프트
  nodes.py    # 노드 4개: generate_query, search, evaluate, write_report
  graph.py    # 그래프 조립 (조건부 엣지로 루프)
main.py       # CLI 실행
langgraph.json  # LangGraph Studio용 설정
```

## 실행 (uv)
```powershell
cd C:\langgraph-research-agent
uv sync                      # .venv 생성 + 의존성 설치
copy .env.example .env       # 그다음 .env에 API 키 입력
uv run main.py "LangGraph 최신 기능은?"
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

## 다음 단계
1. `Send`로 검색어 여러 개 병렬 검색
2. `MemorySaver` 체크포인터로 대화 이어 가기
3. `interrupt`로 보고서 작성 전 사용자 승인
4. Streamlit UI 붙이기

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
