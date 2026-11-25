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

## 구조
- `src/api.js` : LangGraph SDK로 스레드 생성 + `updates` 모드 스트리밍
- `src/App.jsx` : 화면 상태 관리 (세션, 진행 단계, 출처, 보고서)
- `src/components/` : Sidebar, Composer(입력창), ProgressPanel(진행 과정), SourcesPanel(출처)
- `vite.config.js` : `/api` → `http://127.0.0.1:2024` 프록시 (CORS 회피)
