"""Deterministic project-level split.

Splitting by project (not by finding) is the only way to prevent the same
source repository from appearing in both development and evaluation data.
"""

import hashlib
from typing import Iterable


def _score(project: str, seed: str) -> str:
    return hashlib.sha256(f"{seed}\x1f{project}".encode("utf-8")).hexdigest()


def deterministic_split(
    projects: Iterable[str],
    dev_ratio: float = 0.5,
    seed: str = "leakagent-v1",
) -> tuple[list[str], list[str]]:
    """Return (dev_projects, test_projects) as sorted lists.

    The split is deterministic given (project, seed). Re-running on the same
    inputs produces the same partition, which is required for reproducibility.
    """
    if not 0.0 < dev_ratio < 1.0:
        raise ValueError(f"dev_ratio must be in (0, 1); got {dev_ratio}")
    unique = sorted({p for p in projects if p})
    if not unique:
        return [], []
    scored = sorted((_score(p, seed), p) for p in unique)
    n_dev = int(round(len(scored) * dev_ratio))
    if len(scored) > 1:
        n_dev = min(max(n_dev, 1), len(scored) - 1)
    dev = sorted(p for _, p in scored[:n_dev])
    test = sorted(p for _, p in scored[n_dev:])
    return dev, test