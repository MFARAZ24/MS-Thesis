"""Prompt templates for LeakAgent."""

from .candidates import InvestigationCase
from .evidence import EvidenceBundle
from .strategies import get_strategy

SYSTEM_PROMPT = """You are LeakAgent, a careful Android code reviewer. A static analyzer has flagged a candidate memory leak in an Android repository. Your job is to decide whether that warning is correct, using the source evidence you are given.

Treat the analyzer explanation as an unverified hypothesis. Check whether the suspected object actually retains UI and whether relevant cleanup occurs. A class name containing Fragment or View is not proof of UI retention. Imports and method parameters alone do not establish stored references. Missing code in a truncated snippet is not proof that cleanup is absent. If essential type, ownership, or lifecycle evidence is unavailable, return inconclusive.

Produce a single JSON object and no surrounding text.

Schema:
{
  "facts": ["<fact 1>", "<fact 2>", ...],
  "decision": "confirmed_leak" | "likely_leak" | "properly_released" | "false_positive_warning" | "inconclusive",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<one or two sentences connecting the facts to the decision>",
  "cited_code": [{"path": "<path>", "lines": "<range>", "quote": "<verbatim from evidence>"}],
  "cited_docs": [{"doc_id": "<slug>", "quote": "<verbatim from evidence>"}]
}

Decision definitions:
- "confirmed_leak": cleanup is missing or the stored object holds a UI reference and is never cleared.
- "likely_leak": same as above but one detail is ambiguous.
- "properly_released": cleanup is visibly present, or the stored object does not retain UI. Use this to reject false positives you can prove.
- "false_positive_warning": the precondition itself does not hold (for example the analyzer says Activity but the class is a POJO). Do NOT use this merely because cleanup is missing.
- "inconclusive": the evidence does not show enough to decide.

Rules:
- Missing cleanup in a visible lifecycle method is NEVER false_positive_warning. It is confirmed_leak or likely_leak.
- Do not invent line numbers, method names, or cleanup calls. Every cited quote must be verbatim from the evidence.
- If the lifecycle method that should contain the cleanup is not in the evidence, return inconclusive.
- If you cite documentation, it must be relevant to the decision. Zero docs cited is fine.
"""


def _fmt_code_block(block) -> str:
    header = f"=== CODE ({block.role}): {block.path} (lines {block.lines_label}) ==="
    numbered = "\n".join(
        f"{number}: {line}"
        for number, line in enumerate(
            block.text.splitlines(), start=block.line_start
        )
    )
    return f"{header}\n{numbered}\n"


def _fmt_doc_block(doc) -> str:
    return f"=== DOC: {doc.title} [{doc.doc_id}] ===\n{doc.url}\n{doc.snippet}\n"


def build_user_prompt(case: InvestigationCase, evidence: EvidenceBundle) -> str:
    strategy = get_strategy(case.detector)
    lines: list[str] = []

    lines.append("Static analyzer finding")
    lines.append(f"- case_id: {case.case_id}")
    lines.append(f"- detector: {case.detector}")
    lines.append(f"- project: {case.project}")
    lines.append(f"- class: {case.class_name}")
    if case.method_name:
        lines.append(f"- method: {case.method_name}")
    lines.append("")
    lines.append("Analyzer explanation")
    lines.append(case.raw_explanation.strip() or "(none)")
    lines.append("")

    if strategy.focus_prompt:
        lines.append("Detector-specific guidance")
        lines.append(strategy.focus_prompt)
        lines.append("")

    if evidence.notes:
        lines.append("Evidence coverage and limitations")
        lines.extend(f"- {note}" for note in evidence.notes)
        lines.append("")

    lines.append("Repository source evidence")
    if not evidence.code:
        lines.append("(no source file could be resolved for this case)")
    else:
        for block in evidence.code:
            lines.append(_fmt_code_block(block))

    if evidence.api_hits:
        lines.append("Cleanup-related API calls found in this project")
        for hit in evidence.api_hits:
            lines.append(f"  {hit.path}:{hit.line_number}: {hit.line}")
        lines.append("")

    if evidence.docs:
        lines.append("Official Android documentation")
        for doc in evidence.docs:
            lines.append(_fmt_doc_block(doc))
    else:
        lines.append("Official Android documentation")
        lines.append("(no documentation matched the query)")
        lines.append("")

    lines.append(
        "Evaluate only the object or resource identified in the analyzer warning. "
        "Do not substitute unrelated fields or general code-quality concerns. "
        "For code citations, copy the exact path from a CODE header, use actual "
        "numeric source line ranges, and copy source text verbatim without the "
        "displayed line-number prefix. Do not cite headings, summaries, or "
        "placeholder comments. If no supporting quote is available, use an "
        "empty citation list and choose inconclusive. Confidence must be "
        "between 0.0 and 1.0."
    )
    lines.append("Produce the JSON object now. List the facts first, then choose the decision.")
    return "\n".join(lines)