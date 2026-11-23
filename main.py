import sys

from research_agent.graph import graph


def main() -> None:
    question = " ".join(sys.argv[1:]) or input("질문을 입력하세요: ")
    # stream_mode="updates": 노드가 끝날 때마다 바뀐 값을 보여 준다
    final = {}
    for update in graph.stream({"question": question, "loop_count": 0}, stream_mode="updates"):
        for node, values in update.items():
            print(f"▶ {node}")
            if node == "generate_query":
                print(f"   검색어: {values['queries'][-1]}")
            elif node == "evaluate":
                print(f"   충분함: {values['is_sufficient']}  부족: {values['missing_info']}")
            final.update(values)
    print("\n" + "=" * 60 + "\n")
    print(final.get("report", ""))


if __name__ == "__main__":
    main()
