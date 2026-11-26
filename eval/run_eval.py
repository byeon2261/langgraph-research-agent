"""리서치 에이전트 품질 평가.

  uv run python -m eval.run_eval                          # 10문항 × no_plan, baseline, improved
  uv run python -m eval.run_eval --repeat 3               # 3회 반복해 평균 ± 표준편차
  uv run python -m eval.run_eval --limit 3 --no-judge     # 빠르고 싸게 (LLM 심판 끔)
  uv run python -m eval.run_eval --variants improved mini_eval
  uv run python -m eval.run_eval --langsmith              # LangSmith에 데이터셋·실험 기록

결과: eval/results/<시각>.md (비교표) + .json (원자료)
"""
import argparse
import os
import inspect
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import research_agent.nodes as n
from research_agent.graph import build_graph

from eval.evaluators import MEASURE_KEYS, QUALITY_KEYS, RULE_EVALUATORS, make_llm_judges
from eval.variants import DEFAULT_VARIANTS, DESCRIPTIONS, VARIANTS

ROOT = Path(__file__).parent
DATASET = ROOT / "dataset.json"
RESULTS_DIR = ROOT / "results"
LABELS = {
    "aspect_coverage": "관점 커버율 (LLM 심판)",
    "groundedness": "근거 일치율 (LLM 심판)",
    "numeric_grounding": "수치 근거율",
    "citation_validity": "인용 번호 유효율",
    "citation_coverage": "인용 포함 문장 비율",
    "subq_coverage": "하위 질문 근거 확보율",
    "source_diversity": "출처 다양성",
    "num_searches": "검색 횟수",
    "num_rounds": "검색 라운드",
    "latency_sec": "소요 시간(초)",
    "revised_sentences": "검사로 고친 문장 수",
}


def load_dataset(limit: int | None = None) -> list[dict]:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    return data[:limit] if limit else data


# ---------- 평가 대상: 질문 하나를 그래프로 실행 ----------
def make_target(variant_cfg: dict):
    graph = build_graph()
    cfg = {"configurable": variant_cfg, "recursion_limit": 60}
    settings = n.get_settings(cfg)

    def target(inputs: dict) -> dict:
        t0 = time.perf_counter()
        state = graph.invoke({"question": inputs["question"], "review": False, "loop_count": 0}, cfg)
        evidence = [
            {"n": i, "title": r.get("title"), "content": r.get("content")}
            for i, r in enumerate(n._select(state, settings), 1)
        ]
        return {
            "report": state.get("report", ""),
            "sources": state.get("sources", []),
            "sub_questions": state.get("sub_questions", []),
            "covered": state.get("covered", []),
            "loop_count": state.get("loop_count", 0),
            "num_searches": len(state.get("queries", [])),
            "search_errors": state.get("search_errors", []),
            "revised_sentences": state.get("revised_sentences", 0),
            "unverified_claims": state.get("unverified_claims", []),
            "evidence": evidence,
            "latency_sec": time.perf_counter() - t0,
        }

    return target


# ---------- 평가 함수 호출 (LangSmith와 같은 인자 규칙) ----------
def call_evaluator(fn, inputs, outputs, reference_outputs) -> list[dict]:
    avail = {"inputs": inputs, "outputs": outputs, "reference_outputs": reference_outputs}
    params = inspect.signature(fn).parameters
    res = fn(**{k: v for k, v in avail.items() if k in params})
    return res["results"] if isinstance(res, dict) and "results" in res else [res]


def score_one(evaluators, example: dict, outputs: dict) -> dict:
    inputs = {"question": example["question"]}
    ref = {"aspects": example.get("aspects", [])}
    scores, comments = {}, {}
    for ev in evaluators:
        try:
            for r in call_evaluator(ev, inputs, outputs, ref):
                scores[r["key"]] = r.get("score")
                if r.get("comment"):
                    comments[r["key"]] = r["comment"]
        except Exception as e:  # noqa: BLE001 - 평가 하나가 실패해도 나머지는 계속
            comments[getattr(ev, "__name__", "evaluator")] = f"평가 오류: {e}"
    return {"scores": scores, "comments": comments}


# ---------- 로컬 실행 ----------
def run_local(examples, variants, evaluators, concurrency: int, repeat: int = 1) -> list[dict]:
    rows = []
    jobs = [(rep, ex) for rep in range(1, repeat + 1) for ex in examples]
    for name in variants:
        target = make_target(VARIANTS[name])
        print(f"\n== {name}: {DESCRIPTIONS.get(name, '')}")

        def work(job):
            rep, ex = job
            try:
                out = target({"question": ex["question"]})
                res = score_one(evaluators, ex, out)
                err = None
            except Exception as e:  # noqa: BLE001
                out, res, err = {}, {"scores": {}, "comments": {}}, str(e)
            mark = "x" if err else "ok"
            print(f"  [{mark}] {ex['id']} #{rep}  " + " ".join(f"{k}={v}" for k, v in res["scores"].items() if k in QUALITY_KEYS[:3]))
            return {"variant": name, "rep": rep, "id": ex["id"], "question": ex["question"], **res, "error": err,
                    "report": out.get("report", ""), "sub_questions": out.get("sub_questions", []),
                    # 수치 검사 결과를 나중에 직접 확인할 수 있도록 근거 자료도 저장
                    "evidence": out.get("evidence", []), "unverified_claims": out.get("unverified_claims", [])}

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            rows.extend(pool.map(work, jobs))
    return rows


# ---------- LangSmith 실행 ----------
def ensure_dataset(client, name: str, examples: list[dict]) -> None:
    if client.has_dataset(dataset_name=name):
        return
    client.create_dataset(name, description="LangGraph 리서치 에이전트 평가용 질문과 꼭 다뤄야 할 관점")
    client.create_examples(
        dataset_name=name,
        examples=[
            {"inputs": {"question": e["question"]}, "outputs": {"aspects": e["aspects"]}, "metadata": {"id": e["id"]}}
            for e in examples
        ],
    )
    print(f"LangSmith 데이터셋 생성: {name} ({len(examples)}문항)")


def run_langsmith(examples, variants, evaluators, concurrency: int, dataset_name: str, repeat: int = 1) -> list[dict]:
    from langsmith import Client, evaluate

    client = Client()
    ensure_dataset(client, dataset_name, load_dataset())
    wanted = {e["id"] for e in examples}
    data = [ex for ex in client.list_examples(dataset_name=dataset_name) if (ex.metadata or {}).get("id") in wanted]

    rows = []
    for name in variants:
        results = evaluate(
            make_target(VARIANTS[name]),
            data=data,
            evaluators=evaluators,
            experiment_prefix=f"research-{name}",
            description=DESCRIPTIONS.get(name, ""),
            metadata={"variant": name, **VARIANTS[name]},
            max_concurrency=concurrency,
            num_repetitions=repeat,
        )
        seen: dict[str, int] = {}
        print(f"  {name}: {results.url if hasattr(results, 'url') else results.experiment_name}")
        for r in results:
            ex, run = r["example"], r["run"]
            scores = {e.key: e.score for e in r["evaluation_results"]["results"]}
            comments = {e.key: e.comment for e in r["evaluation_results"]["results"] if e.comment}
            ex_id = (ex.metadata or {}).get("id")
            seen[ex_id] = seen.get(ex_id, 0) + 1
            rows.append({
                "variant": name, "rep": seen[ex_id], "id": ex_id, "question": ex.inputs["question"],
                "scores": scores, "comments": comments, "error": run.error,
                "report": (run.outputs or {}).get("report", ""), "sub_questions": (run.outputs or {}).get("sub_questions", []),
                "evidence": (run.outputs or {}).get("evidence", []), "unverified_claims": (run.outputs or {}).get("unverified_claims", []),
            })
    return rows


# ---------- 결과 정리 ----------
def _mean(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return statistics.mean(vals) if vals else None


def summarize(rows: list[dict], variants: list[str]) -> dict:
    """설정별 평균. 반복 실행이면 '회차별 평균'들의 평균과 표준편차(_sd)도 계산"""
    summary = {}
    for v in variants:
        vr = [r for r in rows if r["variant"] == v and not r["error"]]
        reps = sorted({r.get("rep", 1) for r in vr})
        summary[v] = {"n": len(vr), "reps": len(reps), "errors": sum(1 for r in rows if r["variant"] == v and r["error"])}
        for k in QUALITY_KEYS + MEASURE_KEYS:
            m = _mean(r["scores"].get(k) for r in vr)
            summary[v][k] = round(m, 3) if m is not None else None
            per_rep = [_mean(r["scores"].get(k) for r in vr if r.get("rep", 1) == rep) for rep in reps]
            per_rep = [x for x in per_rep if x is not None]
            summary[v][k + "_sd"] = round(statistics.stdev(per_rep), 3) if len(per_rep) > 1 else None
    return summary


def to_markdown(rows, variants, summary, meta) -> str:
    fmt = lambda x: "-" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))
    out = [f"# 리서치 에이전트 평가 결과 ({meta['time']})", ""]
    out += [f"- 문항 수: {meta['n_examples']}  ·  반복: {meta.get('repeat', 1)}회  ·  LLM 심판: {meta['judge']}  ·  실행 방식: {meta['mode']}"]
    out += [f"- `{v}`: {DESCRIPTIONS.get(v, '')}" for v in variants] + [""]

    title = "## 요약 (평균 ± 회차 간 표준편차)" if meta.get("repeat", 1) > 1 else "## 요약 (평균)"
    out += [title, "", "| 지표 | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for k in QUALITY_KEYS + MEASURE_KEYS:
        vals = [summary[v].get(k) for v in variants]
        if all(x is None for x in vals):
            continue
        best = None
        nums = [x for x in vals if x is not None]
        if k in QUALITY_KEYS and len(nums) > 1:
            best = max(nums)
        sds = [summary[v].get(k + "_sd") for v in variants]
        cells = []
        for x, sd in zip(vals, sds):
            c = fmt(x) + (f" ± {sd:.2f}" if sd is not None else "")
            cells.append(f"**{c}**" if best is not None and x == best else c)
        out.append(f"| {LABELS.get(k, k)} | " + " | ".join(cells) + " |")
    errs = {v: summary[v]["errors"] for v in variants if summary[v]["errors"]}
    if errs:
        out += ["", f"실행 실패: {errs}"]

    out += ["", "## 문항별 점수" + (" (반복 평균)" if meta.get("repeat", 1) > 1 else ""), ""]
    cols = ["aspect_coverage", "groundedness", "numeric_grounding", "citation_validity", "num_searches", "latency_sec"]
    out += ["| 문항 | 설정 | " + " | ".join(LABELS[c].split(" (")[0] for c in cols) + " |", "|---|---|" + "---|" * len(cols)]
    for ex_id in dict.fromkeys(r["id"] for r in rows):
        for v in variants:
            rs = [x for x in rows if x["id"] == ex_id and x["variant"] == v]
            if not rs:
                continue
            ok = [x for x in rs if not x["error"]]
            if not ok:
                cells = ["실패"] * len(cols)
            else:
                cells = []
                for c in cols:
                    m = _mean(x["scores"].get(c) for x in ok)
                    cells.append(fmt(round(m, 2) if isinstance(m, float) else m))
                if len(ok) < len(rs):
                    cells[-1] += f" (실패 {len(rs) - len(ok)})"
            out.append(f"| {ex_id} | {v} | " + " | ".join(cells) + " |")

    low = [(r, k) for r in rows for k in ("aspect_coverage", "groundedness") if isinstance(r["scores"].get(k), (int, float)) and r["scores"][k] < 0.75]
    if low:
        out += ["", "## 점수가 낮은 항목 (심판 코멘트)", ""]
        for r, k in low:
            comment = " ".join(str(r["comments"].get(k, "")).split())[:300]
            out.append(f"- `{r['variant']}` / {r['id']} #{r.get('rep', 1)} / {LABELS[k]} {r['scores'][k]:.2f}: {comment}")
    return "\n".join(out) + "\n"


def main(argv=None) -> Path:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--variants", nargs="+", default=DEFAULT_VARIANTS, choices=list(VARIANTS))
    p.add_argument("--repeat", type=int, default=1, help="같은 문항을 N회 반복 (평균 ± 표준편차)")
    p.add_argument("--limit", type=int, help="앞에서부터 N문항만")
    p.add_argument("--no-judge", action="store_true", help="LLM 심판 지표 끄기 (비용 절감)")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--langsmith", action="store_true", help="LangSmith에 데이터셋/실험 기록 (LANGSMITH_API_KEY 필요)")
    p.add_argument("--dataset-name", default="research-agent-eval")
    p.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = p.parse_args(argv)

    examples = load_dataset(args.limit)
    evaluators = list(RULE_EVALUATORS) + ([] if args.no_judge else make_llm_judges())
    print(f"문항 {len(examples)}개 × 설정 {args.variants} × {args.repeat}회 · LLM 심판 {'끔' if args.no_judge else '켬'}")

    if args.langsmith:
        rows = run_langsmith(examples, args.variants, evaluators, args.concurrency, args.dataset_name, args.repeat)
    else:
        rows = run_local(examples, args.variants, evaluators, args.concurrency, args.repeat)

    summary = summarize(rows, args.variants)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    meta = {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "n_examples": len(examples), "repeat": args.repeat,
            "judge": "끔" if args.no_judge else os.getenv("JUDGE_MODEL", "gpt-4o"), "mode": "LangSmith" if args.langsmith else "로컬"}
    args.out.mkdir(parents=True, exist_ok=True)
    md_path = args.out / f"{ts}.md"
    md_path.write_text(to_markdown(rows, args.variants, summary, meta), encoding="utf-8")
    (args.out / f"{ts}.json").write_text(
        json.dumps({"meta": meta, "summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n" + md_path.read_text(encoding="utf-8").split("## 문항별")[0])
    print(f"저장: {md_path}")
    return md_path


if __name__ == "__main__":
    main()
