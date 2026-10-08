import hashlib
import re

PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;", re.MULTILINE)
TYPE_RE = re.compile(r"\b(?:public\s+)?(?:abstract\s+|final\s+|sealed\s+)?(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)")
CLASS_EVIDENCE_RE = re.compile(r"(?:Class|Location)\s*:\s*([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\$[A-Za-z_$][\w$]*)?)", re.IGNORECASE)
METHOD_RE = re.compile(r"Method\s*:\s*([^\r\n|]+)", re.IGNORECASE)
LINE_RE = re.compile(r"Line\s*:\s*(\d+)", re.IGNORECASE)

def normalize_source(text: str) -> str:
    return (text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_source(text).encode("utf-8")).hexdigest()

def source_identity(text: str) -> tuple[str, str, str]:
    package_match, type_match = PACKAGE_RE.search(text or ""), TYPE_RE.search(text or "")
    package_name = package_match.group(1) if package_match else ""
    top_level_name = type_match.group(1) if type_match else ""
    qualified_name = f"{package_name}.{top_level_name}" if package_name and top_level_name else top_level_name
    return package_name, top_level_name, qualified_name

def explanation_identity(explanation: str) -> tuple[str, str, int | None]:
    class_match, method_match, line_match = CLASS_EVIDENCE_RE.search(explanation or ""), METHOD_RE.search(explanation or ""), LINE_RE.search(explanation or "")
    class_name = class_match.group(1) if class_match else ""
    method_name = normalize_method(method_match.group(1)) if method_match else ""
    return class_name, method_name, int(line_match.group(1)) if line_match else None

def simple_class(value: str) -> str:
    return (value or "").rsplit(".", 1)[-1].split("$", 1)[0].strip()

def class_leaf(value: str) -> str:
    return (value or "").rsplit(".", 1)[-1].strip()

def normalize_method(value: str) -> str:
    value = (value or "").strip()
    before_paren = value.split("(", 1)[0].strip()
    return before_paren.split()[-1] if before_paren else ""
