import argparse
import json
from pathlib import Path

from .agent.evaluate import evaluate
from .agent.loop import run_case
from .agent.model import list_ollama_models, load_model
from .agent.prepare import prepare_agent
from .agent.repo_tools import RepoTools
from .benchmark import normalize_benchmark
from .docs.bm25 import BM25
from .docs.corpus import fetch_corpus, load_corpus, write_default_manifest
from .findings import normalize_findings
from .source_index import build_source_index


def _show(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_all(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = {
        "source_index": build_source_index(
            Path(config["projects_root"]), Path(config["source_index_db"]), progress=True
        )
    }
    result["findings"] = normalize_findings(
        Path(config["findings_input_dir"]),
        Path(config["normalized_findings"]),
        Path(config["findings_report"]),
        Path(config["source_index_db"]),
    )
    result["benchmark"] = normalize_benchmark(
        Path(config["validation_csv"]),
        Path(config["normalized_findings"]),
        Path(config["normalized_benchmark"]),
        Path(config["benchmark_report"]),
        config.get("validation_label_column", "Annotator_1_Label"),
        config.get(
            "validation_label_provenance",
            "Final adjudicated LeakScope paper label",
        ),
    )
    return result


def _repo_from_config(config_path: Path) -> RepoTools:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return RepoTools(Path(config["source_index_db"]), Path(config["projects_root"]))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="leakagent", description="Prepare LeakScope cases for LeakAgent research."
    )
    commands = root.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index-sources")
    index.add_argument("--projects-root", type=Path, required=True)
    index.add_argument("--db", type=Path, required=True)

    findings = commands.add_parser("normalize-findings")
    findings.add_argument("--input-dir", type=Path, required=True)
    findings.add_argument("--output", type=Path, required=True)
    findings.add_argument("--report", type=Path, required=True)
    findings.add_argument("--source-db", type=Path)

    benchmark = commands.add_parser("normalize-benchmark")
    benchmark.add_argument("--input", type=Path, required=True)
    benchmark.add_argument("--findings", type=Path, required=True)
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument("--report", type=Path, required=True)
    benchmark.add_argument("--label-column", default="Annotator_1_Label")
    benchmark.add_argument(
        "--label-provenance",
        default="Final adjudicated LeakScope paper label",
    )

    run = commands.add_parser("run-all")
    run.add_argument("--config", type=Path, required=True)

    prepare = commands.add_parser(
        "prepare-agent",
        help="Build unified cases and a project-level dev/test split for LeakAgent.",
    )
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, default=Path("data/agent"))
    prepare.add_argument("--dev-ratio", type=float, default=0.5)
    prepare.add_argument("--seed", default="leakagent-v1")

    repo = commands.add_parser("repo", help="Repository retrieval tools.")
    repo_sub = repo.add_subparsers(dest="tool", required=True)

    def _common(tool_parser: argparse.ArgumentParser) -> None:
        tool_parser.add_argument("--config", type=Path, required=True)
        tool_parser.add_argument("--project", required=True)

    read = repo_sub.add_parser("read")
    _common(read)
    read.add_argument("--path", required=True)

    symbol = repo_sub.add_parser("find-symbol")
    _common(symbol)
    symbol.add_argument("--name", required=True)

    method = repo_sub.add_parser("find-method")
    _common(method)
    method.add_argument("--class-name", dest="class_name", required=True)
    method.add_argument("--method", required=True)

    api = repo_sub.add_parser("find-api")
    _common(api)
    api.add_argument("--pattern", required=True)
    api.add_argument("--language", choices=["java", "kotlin"])

    listing = repo_sub.add_parser("list")
    _common(listing)
    listing.add_argument("--language", choices=["java", "kotlin"])

    docs = commands.add_parser("docs", help="Android documentation corpus and BM25 search.")
    docs_sub = docs.add_subparsers(dest="docs_action", required=True)

    init_manifest = docs_sub.add_parser("init-manifest")
    init_manifest.add_argument("--output", type=Path, default=Path("configs/docs.json"))

    fetch = docs_sub.add_parser("fetch")
    fetch.add_argument("--manifest", type=Path, default=Path("configs/docs.json"))
    fetch.add_argument("--out", type=Path, default=Path("data/docs"))
    fetch.add_argument("--delay", type=float, default=0.75)

    search = docs_sub.add_parser("search")
    search.add_argument("--corpus", type=Path, default=Path("data/docs"))
    search.add_argument("--query", required=True)
    search.add_argument("--top", type=int, default=5)

    agent = commands.add_parser("agent", help="LeakAgent model-driven investigation.")
    agent_sub = agent.add_subparsers(dest="agent_action", required=True)

    check = agent_sub.add_parser("check-model")
    check.add_argument("--config", type=Path, required=True)

    run_one = agent_sub.add_parser("run")
    run_one.add_argument("--config", type=Path, required=True)
    run_one.add_argument("--case-id", required=True)
    run_one.add_argument("--no-log", action="store_true")

    eval_cmd = agent_sub.add_parser("eval")
    eval_cmd.add_argument("--config", type=Path, required=True)
    eval_cmd.add_argument("--split", choices=["dev", "test"], default="dev")
    eval_cmd.add_argument("--limit", type=int, default=None)
    eval_cmd.add_argument("--no-log", action="store_true")
    eval_cmd.add_argument("--stratify", action="store_true",
                          help="Use deterministic stratified sampling by detector.")
    eval_cmd.add_argument("--per-detector", type=int, default=3,
                          help="Cases per detector when --stratify is set.")
    eval_cmd.add_argument("--per-label-per-detector", type=int, default=None,
                          help="Cases per (detector, gold label) when --stratify is set.")

    return root


def _run_repo(args: argparse.Namespace) -> dict:
    tools = _repo_from_config(args.config)
    if args.tool == "read":
        text = tools.read_source(args.project, args.path)
        return {
            "project": args.project,
            "path": args.path,
            "found": text is not None,
            "lines": len(text.splitlines()) if text else 0,
            "content": text if text and len(text) < 4000 else None,
        }
    if args.tool == "find-symbol":
        return {
            "hits": [h.to_dict() for h in tools.find_symbol(args.project, args.name)]
        }
    if args.tool == "find-method":
        return {
            "hits": [
                h.to_dict()
                for h in tools.find_method(args.project, args.class_name, args.method)
            ]
        }
    if args.tool == "find-api":
        return {
            "hits": [
                h.to_dict()
                for h in tools.find_api_calls(
                    args.project, args.pattern, language=args.language
                )
            ]
        }
    if args.tool == "list":
        return {"files": tools.list_project_files(args.project, language=args.language)}
    raise ValueError(f"Unknown repo tool: {args.tool}")


def _run_docs(args: argparse.Namespace) -> dict:
    if args.docs_action == "init-manifest":
        write_default_manifest(args.output)
        return {"manifest_written": str(args.output)}
    if args.docs_action == "fetch":
        return fetch_corpus(args.manifest, args.out, delay=args.delay)
    if args.docs_action == "search":
        docs = load_corpus(args.corpus)
        index = BM25()
        for doc in docs:
            index.add(doc)
        hits = index.search(args.query, top_k=args.top)
        return {
            "corpus": str(args.corpus),
            "documents": len(docs),
            "query": args.query,
            "hits": [h.to_dict() for h in hits],
        }
    raise ValueError(f"Unknown docs action: {args.docs_action}")


def _agent_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_docs_index(docs_dir: Path) -> BM25:
    index = BM25()
    for doc in load_corpus(docs_dir):
        index.add(doc)
    return index


def _run_agent(args: argparse.Namespace) -> dict:
    cfg = _agent_config(args.config)

    if args.agent_action == "check-model":
        return {
            "base_url": cfg.get("base_url", "http://localhost:11434"),
            "configured_model": cfg.get("model"),
            "available_models": list_ollama_models(cfg.get("base_url", "http://localhost:11434")),
        }

    from .agent.candidates import load_investigation_cases

    repo = RepoTools(Path(cfg["source_index_db"]), Path(cfg["projects_root"]))
    docs_index = _load_docs_index(Path(cfg["docs_dir"]))
    ollama_options = cfg.get("ollama_options")
    if isinstance(ollama_options, dict):
        pass
    elif ollama_options is not None:
        ollama_options = dict(ollama_options)
    model = load_model(
        cfg["model"],
        base_url=cfg.get("base_url", "http://localhost:11434"),
        timeout=float(cfg.get("timeout_seconds", 600)),
        keep_alive=cfg.get("keep_alive", "30m"),
        options=ollama_options,
    )
    collector_kwargs = {
        "max_code_blocks": int(cfg.get("max_code_blocks", 3)),
        "max_docs": int(cfg.get("max_docs", 4)),
    }
    log_dir = None if args.no_log else Path(cfg.get("log_dir", "data/agent/runs"))

    if args.agent_action == "run":
        cases = load_investigation_cases(Path(cfg["cases_path"]), Path(cfg["gold_path"]))
        selected = [c for c in cases if c.case_id == args.case_id]
        if not selected:
            raise SystemExit(f"Case not found: {args.case_id}")
        result = run_case(
            case=selected[0],
            repo_tools=repo,
            docs_index=docs_index,
            model=model,
            collector_kwargs=collector_kwargs,
            log_dir=log_dir,
        )
        return result.to_dict()

    if args.agent_action == "eval":
        split = args.split
        cases_path = Path(cfg["cases_path"])
        gold_key = f"{split}_gold_path"
        gold_path = Path(cfg[gold_key]) if gold_key in cfg else Path(cfg["gold_path"])
        cases = load_investigation_cases(cases_path, gold_path)
        split_projects_path = Path("data/agent/split.json")
        if split_projects_path.is_file():
            split_meta = json.loads(split_projects_path.read_text(encoding="utf-8"))
            keep = set(split_meta[f"{split}_projects"])
            cases = [c for c in cases if c.project in keep]

        if getattr(args, "stratify", False):
            from .agent.sample import describe_sample, stratified_sample
            cases = stratified_sample(
                cases,
                per_detector=int(args.per_detector),
                per_label_per_detector=args.per_label_per_detector,
            )
            print(f"Stratified sample: {len(cases)} cases")
            print(json.dumps(describe_sample(cases), indent=2))

        def progress(i, total, r):
            print(
                f"[{i}/{total}] {r.case_id} {r.detector} gold={r.gold_label} "
                f"pred={r.predicted_label} decision={r.decision} conf={r.confidence:.2f}",
                flush=True,
            )

        return evaluate(
            cases=cases,
            repo_tools=repo,
            docs_index=docs_index,
            model=model,
            collector_kwargs=collector_kwargs,
            log_dir=log_dir,
            limit=args.limit,
            on_progress=progress,
        )

    raise ValueError(f"Unknown agent action: {args.agent_action}")


def main() -> None:
    args = parser().parse_args()
    if args.command == "index-sources":
        result = build_source_index(args.projects_root, args.db, progress=True)
    elif args.command == "normalize-findings":
        result = normalize_findings(args.input_dir, args.output, args.report, args.source_db)
    elif args.command == "normalize-benchmark":
        result = normalize_benchmark(
            args.input,
            args.findings,
            args.output,
            args.report,
            args.label_column,
            args.label_provenance,
        )
    elif args.command == "run-all":
        result = _run_all(args.config)
    elif args.command == "prepare-agent":
        config = json.loads(args.config.read_text(encoding="utf-8"))
        result = prepare_agent(
            cases_path=Path(config["normalized_findings"]),
            gold_path=Path(config["normalized_benchmark"]),
            output_dir=args.output_dir,
            dev_ratio=args.dev_ratio,
            seed=args.seed,
        )
    elif args.command == "repo":
        result = _run_repo(args)
    elif args.command == "docs":
        result = _run_docs(args)
    elif args.command == "agent":
        result = _run_agent(args)
    else:
        raise SystemExit(f"Unknown command: {args.command}")
    _show(result)


if __name__ == "__main__":
    main()