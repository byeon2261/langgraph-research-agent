# LangGraph 리서치 에이전트

2단원에서 배운 langgragh를 이용한 프로젝트 중엔 첫번째.

1. 리서치 에이전트 (입문 추천)
2. 이력서 ↔ 채용공고 매칭 코치
3. 개인 문서 Q&A 챗봇 (Adaptive RAG)
4. 멀티 에이전트 여행 플래너 (도전)

## 

**1단계: State 설계**
모든 노드가 같이 읽고 쓰는 데이터예요.

- question: 사용자 질문
- queries: 생성한 검색어 목록
- results: 누적된 검색 결과
- is_sufficient: 평가 결과
- loop_count: 무한 루프를 막는 카운터
- report: 최종 보고서

**2단계: 노드 4개**

- generate_query: LLM이 질문과 지금까지 모은 결과를 보고 다음 검색어를 만들어요
- search: Tavily 같은 검색 API를 호출해요
- evaluate: LLM이 "답하기에 충분한가?"를 판단해요 (structured output으로 bool과 부족한 점을 받기)
- write_report: 출처를 붙여 보고서를 작성해요

**3단계: 핵심 뼈대 코드**

질문 → 검색어 생성 → 웹 검색 → 충분성 평가 → (부족하면 재검색, 최대 3회) → 보고서 작성

**4단계: 확장 로드맵**

- 위 기본형을 완성하고 LangGraph Studio로 흐름 확인하기
- Send로 검색어 여러 개를 병렬 검색하기
- 체크포인터(MemorySaver)를 붙여 대화 이어 가기
- 보고서 작성 전에 interrupt를 넣어 사용자가 목차를 승인하게 하기
- Streamlit이나 FastAPI로 UI 붙이기

