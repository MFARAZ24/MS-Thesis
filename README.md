# LeakAgent ingestion starter

This standalone project preserves LeakScope as the unchanged static candidate generator and prepares its outputs for repository-grounded LeakAgent experiments.

## Inputs

- Canonical LeakScope artifact: `C:/Users/Ali Ali/Desktop/atish/AndroidBuild/artifact`
- Android repositories: `C:/Users/Ali Ali/Desktop/atish/AndroidBuild/successful_projects`
- Validated 388-case CSV: `data/benchmark/raw/leakscope_validated_388.csv`

The original `AndroidBuild` workspace is read-only. Generated databases, normalized JSONL files, and reports stay inside this project.

## Setup on Windows

```powershell
Set-Location "C:\Users\Ali Ali\Desktop\Faraz\LeakAgent"
Copy-Item configs\local.example.json configs\local.json
uv sync
uv run python -m unittest discover -s tests -v
```

The validated 388-case CSV is included at `data/benchmark/raw/leakscope_validated_388.csv`. Run the complete ingestion pipeline with:

```powershell
uv run leakagent run-all --config configs\local.json
```

## Outputs

- `data/manifests/source_index.sqlite`: Java/Kotlin source index for all project folders.
- `data/normalized/leakscope_cases.jsonl`: one normalized record for every raw LeakScope detector case.
- `data/normalized/normalization_report.json`: detector counts, source mapping rates, and duplicates.
- `data/benchmark/processed/leakscope_gold_388.jsonl`: normalized reviewed benchmark with canonical detector and label names.
- `data/benchmark/processed/benchmark_report.json`: label distribution, candidate linkage, and submitted-paper Table VII check.

## Required validation checks

The expected raw total is 2,948 cases. The expected validated distribution is 352 TP, 33 FP, and 3 UNSURE. The benchmark report must set `matches_submitted_paper_table_vii` to `true`. Source mapping results must be reported rather than silently guessed.

## Research interpretation

The 2,948 raw outputs are detector candidates. The 388 reviewed rows provide gold labels for the sampled cases. Fragment retention has 684 raw candidates but 80 validated cases; these counts represent different populations.
