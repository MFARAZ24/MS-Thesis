"""Deterministic stratified sampling for LeakAgent evaluation."""

import hashlib
from collections import defaultdict

from .candidates import InvestigationCase


def _stable_key(case_id: str, seed: str) -> str:
    return hashlib.sha256(f"{seed}\x1f{case_id}".encode("utf-8")).hexdigest()


def stratified_sample(
    cases: list[InvestigationCase],
    per_detector: int = 3,
    per_label_per_detector: int | None = None,
    seed: str = "leakagent-v1",
) -> list[InvestigationCase]:
    """Return a deterministic stratified subset of gold cases.

    If per_label_per_detector is set, sampling is per (detector, gold label).
    Otherwise it is per detector. The subset is stable across runs.
    """
    gold = [c for c in cases if c.is_gold and c.gold_label]
    if not gold:
        return []

    if per_label_per_detector is None:
        buckets: dict = defaultdict(list)
        for c in gold:
            buckets[c.detector].append(c)
        selected: list[InvestigationCase] = []
        for detector in sorted(buckets):
            items = sorted(buckets[detector], key=lambda c: _stable_key(c.case_id, seed))
            selected.extend(items[:per_detector])
        return selected

    buckets2: dict = defaultdict(list)
    for c in gold:
        buckets2[(c.detector, c.gold_label)].append(c)
    selected2: list[InvestigationCase] = []
    for key in sorted(buckets2):
        items = sorted(buckets2[key], key=lambda c: _stable_key(c.case_id, seed))
        selected2.extend(items[:per_label_per_detector])
    return selected2


def describe_sample(cases: list[InvestigationCase]) -> dict:
    """Return a small summary of what the sample contains."""
    by_detector: dict = defaultdict(lambda: {"total": 0, "TP": 0, "FP": 0, "UNSURE": 0})
    for c in cases:
        bucket = by_detector[c.detector]
        bucket["total"] += 1
        if c.gold_label in bucket:
            bucket[c.gold_label] += 1
    return {k: dict(v) for k, v in sorted(by_detector.items())}