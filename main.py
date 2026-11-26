"""CLI 실행: 같은 thread에서 후속 질문을 이어 갈 수 있다 (SQLite 체크포인터).

uv run main.py                 # 대화형 (후속 질문 가능)
uv run main.py "질문"          # 질문 하나로 시작
uv run main.py --auto "질문"   # 하위 질문 승인 단계 건너뛰기
uv run main.py --thread abc    # 이전 대화(thread) 이어 가기
"""
import argparse
import sqlite3
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from research_agent.graph import build_graph

DB_PATH = "checkpoints.sqlite"


def ask_review(payload: dict):
    print("\n[계획 확인] " + payload["message"])
    subs = payload["sub_questions"]
    for i, (s, q) in enumerate(zip(subs, payload["queries"]), 1):
        print(f"  {i}. {s}   (검색어: {q})")
    print("  Enter = 승인 / '번호 새문장' = 수정 / '-번호' = 삭제 / '+새문장' = 추가 (여러 개는 ; 로 구분)")
    line = input("> ").strip()
    if not line:
        return True
    subs = list(subs)
    for cmd in [c.strip() for c in line.split(";") if c.strip()]:
        if cmd.startswith("+"):
            subs.append(cmd[1:].strip())
        elif cmd.startswith("-") and cmd[1:].strip().isdigit():
            idx = int(cmd[1:]) - 1
            if 0 <= idx < len(subs):
                subs[idx] = ""
        else:
            no, _, text = cmd.partition(" ")
            if no.isdigit() and text and 0 <= int(no) - 1 < len(subs):
                subs[int(no) - 1] = text.strip()
    return {"sub_questions": [s for s in subs if s]}


def run(graph, config, payload) -> dict:
    final, streaming = {}, False
    while True:
        interrupted = None
        # [7] updates(노드 진행) + messages(보고서 토큰 스트리밍)를 함께 받는다
        for mode, data in graph.stream(payload, config, stream_mode=["updates", "messages"]):
            if mode == "messages":
                chunk, meta = data
                if meta.get("langgraph_node") == "write_report" and chunk.content:
                    if not streaming:
                        print("\n" + "=" * 60 + "\n")
                        streaming = True
                    print(chunk.content, end="", flush=True)
                continue
            for node, values in data.items():
                if node == "__interrupt__":
                    interrupted = values[0].value
                    continue
                values = values or {}
                print(("\n" if streaming else "") + f"▶ {node}")
                if node == "review_plan":
                    for t in values.get("pending_queries", []):
                        print(f"   {t['sub_question']}  →  “{t['query']}”")
                elif node == "generate_query":
                    for t in values.get("pending_queries", []):
                        print(f"   재검색: “{t['query']}”")
                elif node == "search":
                    r = values.get("results", [])
                    errs = values.get("search_errors", [])
                    print(f"   결과 {len(r)}건" + (f"  (오류: {errs[0]})" if errs else ""))
                elif node == "verify_report":
                    k = values.get("revised_sentences", 0)
                    print("   " + (f"근거 자료에 없는 수치가 있는 문장 {k}개를 고쳤어요" if k else "모든 수치가 근거 자료와 일치해요"))
                    final.update(values)
                    continue
                elif node == "evaluate":
                    subs = final.get("sub_questions", [])
                    for q, ok in zip(subs, values["covered"]):
                        print(f"   {'✓' if ok else '✗'} {q}")
                    for n in values["rule_notes"]:
                        print(f"   ! {n}")
                final.update(values)
        if interrupted is None:
            break
        payload = Command(resume=ask_review(interrupted))  # [6] 승인/수정 값으로 재개

    if final.get("revised_sentences"):
        print("\n" + "=" * 60 + "\n[고친 보고서]\n")
        print(final.get("report", ""))
    for c in final.get("unverified_claims", []):
        print(f"   ! 여전히 근거를 못 찾은 문장: {c}")

    print("\n\n출처")
    for s in final.get("sources", []):
        print(f"  [{s['n']}] {s['title']}  {s['url']}")
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="*")
    parser.add_argument("--auto", action="store_true", help="하위 질문 승인 단계 건너뛰기")
    parser.add_argument("--thread", help="이어 갈 thread id")
    args = parser.parse_args()

    # [5] SQLite 체크포인터: 프로그램을 껐다 켜도 --thread로 이전 대화를 이어 갈 수 있다
    with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
        graph = build_graph(checkpointer=SqliteSaver(conn))
        thread_id = args.thread or uuid.uuid4().hex[:8]
        config = {"configurable": {"thread_id": thread_id}}
        print(f"thread: {thread_id}  (이어 가려면 --thread {thread_id})")

        question = " ".join(args.question)
        while True:
            question = question or input("\n질문 (Enter = 종료): ").strip()
            if not question:
                break
            run(graph, config, {"question": question, "review": not args.auto, "loop_count": 0})
            question = ""  # 다음 입력은 같은 thread의 후속 질문


if __name__ == "__main__":
    main()
