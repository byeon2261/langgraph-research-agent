"""저장된 평가 결과(.json)로 수치 검사를 다시 돌려, 걸린 문장과 이유를 보여 준다.
검사 규칙을 바꾼 뒤 오탐(근거가 있는데 걸린 경우)이 얼마나 되는지 사람이 확인하는 용도.

  uv run python -m eval.check_numbers eval/results/20261126-1016.json
  uv run python -m eval.check_numbers eval/results/<파일>.json --variant improved --limit 20
"""
import argparse
import json
from pathlib import Path

from research_agent.nodes import check_report_numbers
from research_agent.numbers import REASON_KO


def main(argv=None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    p.add_argument("--variant")
    p.add_argument("--limit", type=int, default=30, help="보여 줄 문장 수")
    args = p.parse_args(argv)

    rows = json.loads(args.path.read_text(encoding="utf-8"))["rows"]
    rows = [r for r in rows if not r.get("error") and (not args.variant or r["variant"] == args.variant)]
    if not any(r.get("evidence") for r in rows):
        print("이 결과 파일에는 근거 자료(evidence)가 저장되어 있지 않아요. 새로 평가를 돌린 결과 파일로 실행하세요.")
        return

    total = flagged = shown = 0
    for r in rows:
        n, bad = check_report_numbers(r.get("report", ""), r.get("evidence", []))
        total += n
        flagged += len(bad)
        for b in bad:
            if shown >= args.limit:
                continue
            shown += 1
            reasons = ", ".join(f"{t}: {REASON_KO[x]}" for t, x in zip(b["numbers"], b["reasons"]))
            print(f"[{r['variant']} / {r['id']} #{r.get('rep', 1)}] {reasons}\n   {b['sentence']}\n")
    rate = (1 - flagged / total) if total else 1.0
    print(f"수치 문장 {total}개 중 {flagged}개 걸림 → 수치 근거율 {rate:.2f}")


if __name__ == "__main__":
    main()
