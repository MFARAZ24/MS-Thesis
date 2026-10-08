"""LeakAgent investigation layer: candidates, splits, repository tools, docs, model, loop."""

from .candidates import (
    DETECTOR_RECOMMENDATION,
    InvestigationCase,
    load_investigation_cases,
)
from .decide import Decision, decide
from .evaluate import evaluate
from .evidence import EvidenceBundle, EvidenceCollector
from .loop import CaseResult, run_case
from .model import GenerationResult, Model, OllamaModel, list_ollama_models, load_model
from .prepare import prepare_agent
from .repo_tools import ApiCallHit, MethodHit, RepoTools, SymbolHit
from .split import deterministic_split
from .verify import REQUIRED_CLEANUP_TOKENS, VerificationResult, verify

__all__ = [
    "DETECTOR_RECOMMENDATION",
    "InvestigationCase",
    "load_investigation_cases",
    "prepare_agent",
    "deterministic_split",
    "RepoTools",
    "SymbolHit",
    "MethodHit",
    "ApiCallHit",
    "EvidenceBundle",
    "EvidenceCollector",
    "Decision",
    "decide",
    "CaseResult",
    "run_case",
    "evaluate",
    "Model",
    "OllamaModel",
    "GenerationResult",
    "load_model",
    "list_ollama_models",
    "REQUIRED_CLEANUP_TOKENS",
    "VerificationResult",
    "verify",
]