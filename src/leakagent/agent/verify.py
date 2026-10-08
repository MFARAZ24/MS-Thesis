"""Claim verification for LeakAgent decisions.

Checks the model's output against the evidence it was given.

Two kinds of check:

1. Cleanup visibility. If the model claims the code performs a cleanup
   ("properly_released") or claims the warning is a false positive
   ("false_positive_warning"), the required cleanup tokens must appear in the
   CODE BLOCKS THE MODEL WAS SHOWN, not just somewhere in the project. Missing
   cleanup in the visible snippet is a leak, not a false positive.

2. Citation integrity. Every code quote the model cites must appear in the
   visible code blocks or the api_hits shown in the evidence.

When a check fails, the decision is overridden to "inconclusive".
"""

import re
from dataclasses import dataclass, field

from .decide import Decision
from .evidence import EvidenceBundle


# For each detector, a list of OR-groups. Every group must have at least one
# match for the cleanup to be considered "visible". Single-element groups
# require that specific token.
REQUIRED_CLEANUP_TOKENS: dict[str, list[list[str]]] = {
    "BillingClientLeakRisk": [["endConnection"]],
    "FragmentViewFieldRetentionLeak": [
        ["onDestroyView"],
        ["binding = null", "binding=null", "unbind", "= null"],
    ],
    "ThreadedUIReference": [
        ["cancel", "shutdownNow", "interrupt", "quit", "lifecycleScope"],
    ],
    "StateHolderLeak": [
        ["onDestroy", "onCleared", "= null", "getApplicationContext", "AndroidViewModel"],
    ],
    "ServiceResourceManagementIssueDetector": [
        ["stopSelf", "stopForeground", "stopService"],
    ],
    "ViewModelContextReference": [
        ["AndroidViewModel", "getApplicationContext"],
    ],
    "ImproperCallbackRegistration": [
        ["LifecycleOwner", "removeCallback"],
    ],
    "FlowRetentionLeak": [
        ["repeatOnLifecycle", "lifecycleScope", "collectLatest"],
    ],
}


@dataclass
class VerificationResult:
    decision: Decision
    overridden: bool = False
    notes: list[str] = field(default_factory=list)
    unverified_citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.to_dict(),
            "overridden": self.overridden,
            "notes": list(self.notes),
            "unverified_citations": list(self.unverified_citations),
        }


def _normalise_whitespace(text) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return re.sub(r"\s+", " ", text).strip()


def _code_only_text(evidence: EvidenceBundle) -> str:
    """Only the code blocks the model was actually shown."""
    return _normalise_whitespace("\n".join(block.text for block in evidence.code))


def _full_text(evidence: EvidenceBundle) -> str:
    """Code blocks plus api hits, for citation checks."""
    parts = [block.text for block in evidence.code]
    for hit in evidence.api_hits:
        parts.append(hit.line)
    return _normalise_whitespace("\n".join(parts))


def _verify_citations(decision: Decision, evidence: EvidenceBundle) -> list[str]:
    unverified = []
    for item in decision.cited_code:
        if not isinstance(item, dict):
            unverified.append("Malformed code citation")
            continue

        path = item.get("path")
        quote = item.get("quote")
        lines = item.get("lines")
        if not all(isinstance(value, str) and value.strip()
                   for value in (path, quote, lines)):
            unverified.append("Missing or invalid citation fields")
            continue

        match = re.fullmatch(r"([1-9][0-9]*)(?:-([1-9][0-9]*))?", lines.strip())
        if not match:
            unverified.append(f"{path}: invalid line range {lines}")
            continue

        first = int(match.group(1))
        last = int(match.group(2) or first)
        if last < first:
            unverified.append(f"{path}: reversed line range")
            continue

        # Build only the source lines actually supplied in the evidence.
        visible = {}
        for block in evidence.code:
            if block.path == path:
                for number, text in enumerate(
                    block.text.splitlines(), start=block.line_start
                ):
                    visible[number] = text
        for hit in evidence.api_hits:
            if hit.path == path:
                visible.setdefault(hit.line_number, hit.line)

        if not visible or last - first + 1 > len(visible):
            unverified.append(f"{path}:{lines}: range outside visible evidence")
            continue
        if any(number not in visible for number in range(first, last + 1)):
            unverified.append(f"{path}:{lines}: range outside visible evidence")
            continue

        source = "\n".join(visible[number] for number in range(first, last + 1))
        if _normalise_whitespace(quote) not in _normalise_whitespace(source):
            unverified.append(f"{path}:{lines}: quote does not match source")

    return unverified


def _cleanup_visible_in_code(detector: str, code_text: str) -> bool:
    """Return True only if every required cleanup group matches in the code."""
    groups = REQUIRED_CLEANUP_TOKENS.get(detector, [])
    if not groups:
        return True
    lower = code_text.lower()
    for group in groups:
        if not any(token.lower() in lower for token in group):
            return False
    return True


def _decision_is_unsupported(decision: str, cleanup_visible: bool) -> str | None:
    if decision == "properly_released" and not cleanup_visible:
        return (
            "Decision was 'properly_released' but the required cleanup is not "
            "visible in the code evidence the model was shown."
        )
    if decision == "false_positive_warning" and not cleanup_visible:
        return (
            "Decision was 'false_positive_warning' but the code evidence shows "
            "no cleanup, which is consistent with a real leak. Missing cleanup "
            "is not the same as a false positive."
        )
    return None


def verify(decision: Decision, evidence: EvidenceBundle) -> VerificationResult:
    if decision.parse_status != "ok":
        return VerificationResult(decision=decision)

    code_text = _code_only_text(evidence)
    full_text = _full_text(evidence)
    cleanup_visible = _cleanup_visible_in_code(evidence.detector, code_text)
    unverified = _verify_citations(decision, evidence)
    notes: list[str] = []
    overridden = False

    if decision.decision != "inconclusive" and not decision.cited_code:
        notes.append("Conclusive decision has no supporting code citations.")
        overridden = True

    reason = _decision_is_unsupported(decision.decision, cleanup_visible)

    if evidence.detector == "StateHolderLeak":
        field_match = re.search(
            r"\bfield\s+'([^']+)'", evidence.warning_explanation
        )
        field_name = field_match.group(1) if field_match else None

        if decision.decision == "properly_released":
            assignment = (
                re.compile(
                    rf"(?<![\w$.])(?:this\.)?{re.escape(field_name)}"
                    r"\s*=(?!=)\s*null\b"
                ) if field_name else None
            )
            released = assignment is not None and any(
                block.role in {"lifecycle:onDestroy", "lifecycle:onCleared",
                               "lifecycle:onDetach"}
                and assignment.search(block.text)
                for block in evidence.code
            )
            reason = None if released else (
                "StateHolder release is unsupported: no direct null assignment "
                "to the flagged field is visible in retrieved lifecycle evidence. "
                "Delegated cleanup remains unresolved."
            )

        elif decision.decision == "false_positive_warning":
            # Cleanup is not required when the retention precondition is false.
            # Require a valid citation to the referenced type as an evidence gate.
            type_blocks = [
                block for block in evidence.code
                if block.role == "referenced_type"
            ]
            supported_type_citation = any(
                citation.get("path") == block.path
                and not _verify_citations(
                    Decision(
                        decision="inconclusive", confidence=0,
                        reasoning="Citation check.",
                        cited_code=[citation],
                    ), evidence
                )
                for citation in decision.cited_code
                if isinstance(citation, dict)
                for block in type_blocks
            )
            reason = None if supported_type_citation else (
                "StateHolder precondition rejection lacks a valid citation "
                "to the referenced-type source."
            )

    if reason:
        notes.append(reason)
        overridden = True

    total_citations = sum(
        1 for c in decision.cited_code if isinstance(c, dict) and c.get("quote")
    )
    if unverified:
        notes.append(
            f"{len(unverified)} of {total_citations} code citations could not "
            f"be located in the evidence."
        )
        overridden = True

    if overridden:
        new_decision = Decision(
            decision="inconclusive",
            confidence=min(decision.confidence, 0.3),
            reasoning=("Claim verification failed: " + " ".join(notes))[:2000],
            facts=decision.facts,
            cited_code=decision.cited_code,
            cited_docs=decision.cited_docs,
            parse_status="verification_failed",
            raw_response=decision.raw_response,
        )
    else:
        new_decision = decision

    return VerificationResult(
        decision=new_decision,
        overridden=overridden,
        notes=notes,
        unverified_citations=unverified,
    )