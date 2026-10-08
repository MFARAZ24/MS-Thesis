"""Fetch and load the local Android documentation corpus."""

import json
import time
import urllib.request
from datetime import date
from pathlib import Path

from .bm25 import Doc
from .html_text import html_to_text

USER_AGENT = "LeakAgent-DocFetcher/0.1 (research; thesis corpus)"

DEFAULT_MANIFEST = {
    "entries": [
        {"slug": "memory-overview", "url": "https://developer.android.com/topic/performance/memory", "title": "Android memory overview"},
        {"slug": "manage-app-memory", "url": "https://developer.android.com/topic/performance/memory/manage-app-memory", "title": "Manage your app's memory"},
        {"slug": "fragment-lifecycle", "url": "https://developer.android.com/guide/fragments/lifecycle", "title": "Fragment lifecycle"},
        {"slug": "view-binding", "url": "https://developer.android.com/topic/libraries/view-binding", "title": "View binding"},
        {"slug": "viewmodel-overview", "url": "https://developer.android.com/topic/libraries/architecture/viewmodel", "title": "ViewModel overview"},
        {"slug": "state-holders", "url": "https://developer.android.com/topic/architecture/ui-layer/stateholders", "title": "State holders and UI state"},
        {"slug": "services-overview", "url": "https://developer.android.com/developer/background-work/services", "title": "Services overview"},
        {"slug": "service-api", "url": "https://developer.android.com/reference/android/app/Service", "title": "Service API reference"},
        {"slug": "threading-performance", "url": "https://developer.android.com/topic/performance/threads", "title": "Better performance through threading"},
        {"slug": "custom-back", "url": "https://developer.android.com/guide/navigation/navigation-custom-back", "title": "Provide custom back navigation"},
        {"slug": "billing-client", "url": "https://developer.android.com/reference/com/android/billingclient/api/BillingClient", "title": "BillingClient reference"},
        {"slug": "window-info-tracker", "url": "https://developer.android.com/reference/android/window/layout/WindowInfoTracker", "title": "WindowInfoTracker reference"},
        {"slug": "lint", "url": "https://developer.android.com/studio/write/lint", "title": "Improve your code with lint checks"},
        {"slug": "activity-lifecycle", "url": "https://developer.android.com/guide/components/activities/activity-lifecycle", "title": "The activity lifecycle"},
    ]
}


def _fetch_url(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def write_default_manifest(path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(DEFAULT_MANIFEST, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_corpus(manifest_path: Path, output_dir: Path, delay: float = 0.75) -> dict:
    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Manifest not found: {manifest_path}. "
            "Run 'leakagent docs init-manifest' first, or create it manually."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = date.today().isoformat()
    written, failed = [], []
    for entry in entries:
        slug = entry["slug"]
        url = entry["url"]
        title = entry.get("title") or slug
        try:
            html = _fetch_url(url)
            text = html_to_text(html)
            if not text:
                raise ValueError("empty text after HTML extraction")
        except Exception as exc:
            failed.append({"slug": slug, "url": url, "error": str(exc)})
            continue
        record = {
            "slug": slug,
            "title": title,
            "url": url,
            "retrieved_at": retrieved_at,
            "version": entry.get("version"),
            "text": text,
        }
        (output_dir / f"{slug}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(slug)
        time.sleep(delay)
    return {
        "manifest": str(manifest_path),
        "output_dir": str(output_dir),
        "retrieved_at": retrieved_at,
        "written": written,
        "failed": failed,
        "written_count": len(written),
        "failed_count": len(failed),
    }


def load_corpus(corpus_dir: Path) -> list[Doc]:
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")
    docs: list[Doc] = []
    for path in sorted(corpus_dir.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        doc_id = rec.get("slug") or path.stem
        docs.append(
            Doc(
                doc_id=doc_id,
                title=rec.get("title", doc_id),
                url=rec.get("url", ""),
                text=rec.get("text", ""),
            )
        )
    return docs