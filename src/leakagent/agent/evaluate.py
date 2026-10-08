"""Aggregate CaseResults into RQ metrics."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from .candidates import InvestigationCase
from .loop import CaseResult, run_case


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def _metrics_for(results: list[CaseResult]) -> dict:
    gold_tp = [r for r in results if r.gold_label == "TP"]
    gold_fp = [r for r in results if r.gold_label == "FP"]
    gold_unsure = [r for r in results if r.gold_label == "UNSURE"]

    tp_retained = sum(1 for r in gold_tp if r.predicted_label == "TP")
    tp_dismissed = sum(1 for r in gold_tp if r.predicted_label == "FP")
    tp_abstained = sum(1 for r in gold_tp if r.predicted_label is None)

    fp_dismissed = sum(1 for r in gold_fp if r.predicted_label == "FP")
    fp_retained = sum(1 for r in gold_fp if r.predicted_label == "TP")
    fp_abstained = sum(1 for r in gold_fp if r.predicted_label is None)

    abstained = sum(1 for r in results if r.predicted_label is None)

    return {
        "n_total": len(results),
        "n_gold_tp": len(gold_tp),
        "n_gold_fp": len(gold_fp),
        "n_gold_unsure": len(gold_unsure),
        "tp_retention_rate": _safe_div(tp_retained, len(gold_tp)),
        "fp_reduction_rate": _safe_div(fp_dismissed, len(gold_fp)),
        "incorrect_dismissal_rate": _safe_div(tp_dismissed, len(gold_tp)),
        "abstention_rate": _safe_div(abstained, len(results)),
        "tp_abstained": tp_abstained,
        "fp_abstained": fp_abstained,
        "fp_retained": fp_retained,
        "decision_distribution": dict(Counter(r.decision for r in results)),
        "parse_error_count": sum(1 for r in results if r.parse_status == "parse_error"),
        "schema_error_count": sum(1 for r in results if r.parse_status == "schema_error"),
        "model_error_count": sum(1 for r in results if r.parse_status == "model_error"),
        "reasoned_abstention_count": sum(
            1 for r in results
            if r.decision == "inconclusive" and r.parse_status == "ok"
        ),
        "verification_override_count": sum(1 for r in results if r.verification_overridden),
    }


def evaluate(
    cases: list[InvestigationCase],
    repo_tools,
    docs_index,
    model,
    collector_kwargs: dict | None = None,
    log_dir: Path | None = None,
    limit: int | None = None,
    on_progress=None,
) -> dict:
    selected = [c for c in cases if c.is_gold and c.gold_label]
    if limit is not None:
        selected = selected[:limit]

    results: list[CaseResult] = []
    for i, case in enumerate(selected, 1):
        result = run_case(
            case=case,
            repo_tools=repo_tools,
            docs_index=docs_index,
            model=model,
            collector_kwargs=collector_kwargs,
            log_dir=log_dir,
        )
        results.append(result)
        if on_progress is not None:
            on_progress(i, len(selected), result)

    by_recommendation = defaultdict(list)
    for r in results:
        by_recommendation[r.detector_recommendation].append(r)

    by_detector = defaultdict(list)
    for r in results:
        by_detector[r.detector].append(r)

    report = {
        "model": model.name,
        "n_cases": len(results),
        "overall": _metrics_for(results),
        "by_recommendation": {
            role: _metrics_for(rows) for role, rows in sorted(by_recommendation.items())
        },
        "by_detector": {
            det: _metrics_for(rows) for det, rows in sorted(by_detector.items())
        },
        "results": [r.to_dict() for r in results],
    }
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "_eval_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report