"""저장된 평가 결과(.json)를 새 심판으로 다시 채점한다. 검색·보고서 생성은 다시 하지 않는다 (LLM 심판 비용만 듦).

  uv run python -m eval.rejudge eval/results/20261126-1411.json              # 근거 일치율만 다시
  uv run python -m eval.rejudge eval/results/20261126-1411.json --aspect     # 관점 커버율도 다시

결과: eval/results/<원본 이름>-rejudged.md / .json
보고서와 근거 자료(evidence)가 저장된 결과 파일만 가능 (2026-11-26 14:11 이후)
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eval.evaluators import make_llm_judges, numeric_grounding
from eval.run_eval import DATASET, summarize, to_markdown


def rejudge_rows(rows: list[dict], judge=None, aspect: bool = False, concurrency: int = 4) -> list[dict]:
    aspect_fn, grounded_fn = make_llm_judges(judge)
    aspects_by_id = {d["id"]: d["aspects"] for d in json.loads(DATASET.read_text(encoding="utf-8"))}

    def work(r: dict) -> dict:
        r = {**r, "scores": dict(r["scores"]), "comments": dict(r["comments"])}
        if r.get("error") or not r.get("evidence"):
            return r
        outputs = {"report": r.get("report", ""), "evidence": r["evidence"]}
        old = r["scores"].get("groundedness")
        results = [grounded_fn(outputs), numeric_grounding(outputs)]
        if aspect:
            results.append(aspect_fn({"question": r["question"]}, outputs, {"aspects": aspects_by_id.get(r["id"], [])}))
        for res in results:
            r["scores"][res["key"]] = res.get("score")
            if res.get("comment"):
                r["comments"][res["key"]] = res["comment"]
        r["scores"]["groundedness_old"] = old
        print(f"  {r['variant']:>10} / {r['id']} #{r.get('rep', 1)}  근거 일치율 {old} → {r['scores']['groundedness']}")
        return r

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(work, rows))


def main(argv=None, judge=None) -> Path:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", type=Path)
    p.add_argument("--aspect", action="store_true", help="관점 커버율도 다시 채점")
    p.add_argument("--concurrency", type=int, default=4)
    args = p.parse_args(argv)

    data = json.loads(args.path.read_text(encoding="utf-8"))
    rows = data["rows"]
    if not any(r.get("evidence") for r in rows):
        raise SystemExit("이 결과 파일에는 근거 자료(evidence)가 없어 다시 채점할 수 없어요. 14:11 이후 결과 파일을 쓰세요.")
    variants = list(dict.fromkeys(r["variant"] for r in rows))
    print(f"{args.path.name}: {len(rows)}건 다시 채점 (근거 일치율{' + 관점 커버율' if args.aspect else ''})")

    new_rows = rejudge_rows(rows, judge=judge, aspect=args.aspect, concurrency=args.concurrency)
    summary = summarize(new_rows, variants)
    old_summary = summarize(rows, variants)
    meta = {**data["meta"], "mode": f"{data['meta'].get('mode', '로컬')} → 재채점(심판 v2: 주장 추출과 판정 분리)"}

    md = to_markdown(new_rows, variants, summary, meta)
    cmp = ["", "## 재채점 전후 (근거 일치율)", "", "| 설정 | 이전 심판 | 새 심판 |", "|---|---|---|"]
    for v in variants:
        cmp.append(f"| {v} | {old_summary[v].get('groundedness')} | {summary[v].get('groundedness')} |")
    md = md.replace("\n## 문항별", "\n".join(cmp) + "\n\n## 문항별", 1)

    out = args.path.with_name(args.path.stem + "-rejudged.md")
    out.write_text(md, encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps({"meta": meta, "summary": summary, "summary_before": old_summary, "rows": new_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n" + md.split("## 문항별")[0])
    print(f"저장: {out}")
    return out


if __name__ == "__main__":
    main()
