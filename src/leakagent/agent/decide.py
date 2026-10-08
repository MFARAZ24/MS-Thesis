"""Single-case decision: build a prompt, call the model, parse JSON."""

import json
import math
import re
from dataclasses import asdict, dataclass, field

from .candidates import InvestigationCase
from .evidence import EvidenceBundle
from .model import Model, ModelError
from .prompts import SYSTEM_PROMPT, build_user_prompt

VALID_DECISIONS = {
    "confirmed_leak",
    "likely_leak",
    "properly_released",
    "false_positive_warning",
    "inconclusive",
}

DECISION_TO_PREDICTED_LABEL = {
    "confirmed_leak": "TP",
    "likely_leak": "TP",
    "properly_released": "FP",
    "false_positive_warning": "FP",
    "inconclusive": None,
}


@dataclass
class Decision:
    decision: str
    confidence: float
    reasoning: str
    facts: list[str] = field(default_factory=list)
    cited_code: list[dict] = field(default_factory=list)
    cited_docs: list[dict] = field(default_factory=list)
    parse_status: str = "ok"
    raw_response: str = ""
    generation_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def predicted_label(self):
        return DECISION_TO_PREDICTED_LABEL.get(self.decision)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _normalise_decision(value: str) -> str:
    value = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in VALID_DECISIONS:
        return value
    return "inconclusive"


def _inconclusive(reasoning: str, status: str, raw: str = "", metadata: dict | None = None) -> Decision:
    return Decision(
        decision="inconclusive",
        confidence=0.0,
        reasoning=reasoning[:2000],
        parse_status=status,
        raw_response=raw,
        generation_metadata=metadata or {},
    )



def _schema_errors(value) -> list[str]:
    if not isinstance(value, dict):
        return ["Response must be a JSON object."]

    errors = []
    required = {
        "facts", "decision", "confidence", "reasoning",
        "cited_code", "cited_docs",
    }
    missing = sorted(required - value.keys())
    if missing:
        errors.append("Missing fields: " + ", ".join(missing))

    decision = value.get("decision")
    if not isinstance(decision, str) or decision not in VALID_DECISIONS:
        errors.append("decision must be an allowed outcome.")

    confidence = value.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        errors.append("confidence must be a finite number between 0 and 1.")

    reasoning = value.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        errors.append("reasoning must be a nonempty string.")

    facts = value.get("facts")
    if not isinstance(facts, list) or any(
        not isinstance(fact, str) or not fact.strip() for fact in facts
    ):
        errors.append("facts must be a list of nonempty strings.")

    for field, keys in (
        ("cited_code", ("path", "lines", "quote")),
        ("cited_docs", ("doc_id", "quote")),
    ):
        citations = value.get(field)
        if not isinstance(citations, list):
            errors.append(f"{field} must be a list.")
            continue
        for index, citation in enumerate(citations):
            if not isinstance(citation, dict) or any(
                not isinstance(citation.get(key), str)
                or not citation[key].strip()
                for key in keys
            ):
                errors.append(f"{field}[{index}] has invalid citation fields.")

    return errors


def decide(case: InvestigationCase, evidence: EvidenceBundle, model: Model) -> Decision:
    user_prompt = build_user_prompt(case, evidence)
    try:
        result = model.generate(user_prompt, system=SYSTEM_PROMPT, json_mode=True)
    except ModelError as exc:
        return _inconclusive(f"Model error: {exc}", "model_error")
    except Exception as exc:
        return _inconclusive(f"Unexpected model exception: {exc}", "model_error")

    metadata = {
        "model": result.model,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_duration_ns": result.total_duration_ns,
        "done": result.raw.get("done"),
        "done_reason": result.raw.get("done_reason"),
        "response_characters": len(result.text or ""),
        "error": result.error,
    }

    if not result.error and not (result.text or "").strip():
        decision = _inconclusive(
            "Model returned an empty response.", "model_error"
        )
        decision.generation_metadata = metadata
        return decision

    if result.error:
        return _inconclusive(
            f"Model returned an error: {result.error}",
            "model_error",
            raw=result.text or "",
            metadata=metadata,
        )

    parsed = _extract_json(result.text)
    if not parsed:
        return _inconclusive(
            "Model response could not be parsed as JSON.",
            "parse_error",
            raw=result.text or "",
            metadata=metadata,
        )

    errors = _schema_errors(parsed)
    if errors:
        return _inconclusive(
            "Invalid response schema: " + " ".join(errors),
            "schema_error",
            raw=result.text or "",
            metadata=metadata,
        )

    decision = parsed["decision"]
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reasoning = str(parsed.get("reasoning", ""))[:2000]
    facts_raw = parsed.get("facts") or []
    if not isinstance(facts_raw, list):
        facts_raw = []
    facts = [str(f) for f in facts_raw]
    cited_code = parsed.get("cited_code") or []
    cited_docs = parsed.get("cited_docs") or []
    if not isinstance(cited_code, list):
        cited_code = []
    if not isinstance(cited_docs, list):
        cited_docs = []
    return Decision(
        decision=decision,
        confidence=confidence,
        reasoning=reasoning,
        facts=facts,
        cited_code=cited_code,
        cited_docs=cited_docs,
        parse_status="ok",
        raw_response=result.text or "",
        generation_metadata=metadata,
    )