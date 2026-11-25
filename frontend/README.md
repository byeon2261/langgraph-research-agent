# Research Agent Frontend (React + Vite)

LangGraph dev 서버에 연결해 리서치 진행 과정과 보고서, 출처를 보여 주는 화면입니다.

## 실행
1. 백엔드 먼저 실행 (프로젝트 루트에서)
   ```powershell
   .\dev.ps1
   ```
2. 프런트엔드 실행 (새 터미널)
   ```powershell
   cd C:\langgraph-research-agent\frontend
   npm install
   npm run dev
   ```
3. 브라우저에서 http://localhost:5173 접속

## 테스트
```powershell
npm test   # Vitest: src/lib/turns.test.js
```
화면 상태 로직(`src/lib/turns.js`)은 React와 분리되어 있어 브라우저 없이 테스트돼요.

## 기능
- 검색 전 계획 확인: "검색 전 계획 확인"을 켜면 하위 질문을 고치거나 추가·삭제한 뒤 검색을 시작해요 (LangGraph `interrupt`)
- 후속 질문: 리서치 화면 아래 입력창은 같은 대화(thread)에서 이어서 조사해요
- 보고서 스트리밍: 보고서가 생성되는 대로 실시간 표시
- 출처 번호: 보고서의 `[번호]`를 누르면 해당 출처로 이동 (출처 패널과 번호 일치)
- 기록 저장: 새로고침해도 브라우저에 리서치 기록이 남아요

## 구조
- `src/api.js` : LangGraph SDK로 스레드 생성, `updates` + `messages-tuple` 스트리밍, interrupt 재개(`command.resume`)
- `src/App.jsx` : 화면 상태 관리 (세션, 진행 단계, 출처, 보고서)
- `src/lib/turns.js` : 상태 갱신·출처 링크 변환 순수 함수 (+ `turns.test.js`)
- `src/components/` : Sidebar, Composer(입력창), ProgressPanel(진행 과정), PlanReview(계획 확인), SourcesPanel(출처)
- `vite.config.js` : `/api` → `http://127.0.0.1:2024` 프록시 (CORS 회피)
