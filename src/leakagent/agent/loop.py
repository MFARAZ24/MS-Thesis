"""Run LeakAgent on a single case and log everything needed for reproducibility."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..docs.bm25 import BM25
from .candidates import InvestigationCase
from .decide import Decision, decide
from .evidence import EvidenceBundle, EvidenceCollector
from .model import Model
from .repo_tools import RepoTools
from .verify import verify


@dataclass
class CaseResult:
    case_id: str
    detector: str
    detector_group: str
    detector_recommendation: str
    project: str
    gold_label: str | None
    predicted_label: str | None
    decision: str
    confidence: float
    reasoning: str
    parse_status: str
    verification_overridden: bool = False
    verification_notes: list[str] = field(default_factory=list)
    evidence_counts: dict = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def run_case(
    case: InvestigationCase,
    repo_tools: RepoTools,
    docs_index: BM25,
    model: Model,
    collector_kwargs: dict | None = None,
    log_dir: Path | None = None,
) -> CaseResult:
    started = datetime.now(timezone.utc).isoformat()
    collector = EvidenceCollector(repo_tools, docs_index, **(collector_kwargs or {}))
    evidence: EvidenceBundle = collector.collect(case)
    raw_decision: Decision = decide(case, evidence, model)
    verification = verify(raw_decision, evidence)
    decision = verification.decision
    finished = datetime.now(timezone.utc).isoformat()

    result = CaseResult(
        case_id=case.case_id,
        detector=case.detector,
        detector_group=case.detector_group,
        detector_recommendation=case.detector_recommendation,
        project=case.project,
        gold_label=case.gold_label,
        predicted_label=decision.predicted_label,
        decision=decision.decision,
        confidence=decision.confidence,
        reasoning=decision.reasoning,
        parse_status=decision.parse_status,
        verification_overridden=verification.overridden,
        verification_notes=verification.notes,
        evidence_counts={
            "code_blocks": len(evidence.code),
            "api_hits": len(evidence.api_hits),
            "docs": len(evidence.docs),
        },
        started_at=started,
        finished_at=finished,
        model=model.name,
    )

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "case": case.to_dict(),
            "evidence": evidence.to_dict(),
            "raw_decision": raw_decision.to_dict(),
            "verification": verification.to_dict(),
            "result": result.to_dict(),
        }
        (log_dir / f"{case.case_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result