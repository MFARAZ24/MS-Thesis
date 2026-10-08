"""Model interface for LeakAgent.

The interface is intentionally minimal so that any open-source model runtime
can be plugged in without touching the agent loop. The first implementation
targets Ollama, which exposes a local HTTP API and supports Qwen, Mistral,
Llama, and other instruction/code models.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional



DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "facts": {
            "type": "array",
            "items": {"type": "string"},
        },
        "decision": {
            "type": "string",
            "enum": [
                "confirmed_leak", "likely_leak", "properly_released",
                "false_positive_warning", "inconclusive",
            ],
        },
        "confidence": {
            "type": "number", "minimum": 0, "maximum": 1,
        },
        "reasoning": {"type": "string", "minLength": 1},
        "cited_code": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"},
                    "lines": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["path", "lines", "quote"],
            },
        },
        "cited_docs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "doc_id": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["doc_id", "quote"],
            },
        },
    },
    "required": [
        "facts", "decision", "confidence", "reasoning",
        "cited_code", "cited_docs",
    ],
}


class ModelError(RuntimeError):
    """Raised when the model runtime returns an error we cannot recover from."""


@dataclass
class GenerationResult:
    text: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_duration_ns: Optional[int] = None
    raw: dict = field(default_factory=dict)
    error: Optional[str] = None


class Model:
    name: str = "abstract"

    def generate(self, prompt: str, system: str = "", json_mode: bool = False) -> GenerationResult:
        raise NotImplementedError


class OllamaModel(Model):
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 600.0,
        options: Optional[dict] = None,
        keep_alive: Optional[str] = None,
    ):
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Defaults chosen to discourage small models from looping. Ollama's
        # own repeat_penalty default is 1.1; 1.3 is more aggressive but
        # appropriate for 1-2B parameter models.
        default_options = {"repeat_penalty": 1.3, "repeat_last_n": 128}
        merged = dict(default_options)
        if options:
            merged.update(options)
        self.options = merged
        self.keep_alive = keep_alive

    def generate(self, prompt: str, system: str = "", json_mode: bool = False) -> GenerationResult:
        payload: dict = {"model": self.name, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = DECISION_SCHEMA
        if self.options:
            payload["options"] = self.options
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            # Ollama aborts generation when the model enters a token loop.
            # That is a recoverable condition: return an empty result that
            # the caller will treat as inconclusive.
            if "token repeat limit" in detail or exc.code == 500:
                return GenerationResult(
                    text="",
                    model=self.name,
                    error=f"Ollama HTTP {exc.code}: {detail}",
                )
            raise ModelError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ModelError(
                f"Could not reach Ollama at {self.base_url}. "
                f"Is 'ollama serve' running? ({exc})"
            ) from exc
        except TimeoutError as exc:
            return GenerationResult(
                text="",
                model=self.name,
                error=f"Ollama request timed out after {self.timeout}s",
            )
        return GenerationResult(
            text=body.get("response", ""),
            model=body.get("model", self.name),
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
            total_duration_ns=body.get("total_duration"),
            raw=body,
        )


def list_ollama_models(base_url: str = "http://localhost:11434", timeout: float = 10.0) -> list[str]:
    req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ModelError(f"Could not reach Ollama at {base_url}: {exc}") from exc
    return sorted(m["name"] for m in body.get("models", []))


def load_model(
    name: str,
    base_url: str = "http://localhost:11434",
    timeout: float = 600.0,
    keep_alive: str | None = "30m",
    options: dict | None = None,
) -> Model:
    return OllamaModel(
        model=name,
        base_url=base_url,
        timeout=timeout,
        keep_alive=keep_alive,
        options=options,
    )