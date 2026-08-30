# RAG Eval Sets

This directory holds the curated CTF evaluation manifests for the RAG rollout.

Files:
- `main_100.json`: 100 challenges total
- `smoke_20.json`: 20 quick checks
- `rag_sensitive_100.json`: 100 knowledge-heavy challenges
- `smoke_20_no_character.json`: temporary local smoke subset without Character
- `smoke_20_after_delulu.json`: temporary local smoke subset without the first six Cybench smoke entries

Selection policy:
- `main_100.json` = 57 NYU CTF Bench test challenges + all 43 Cybench benchmark tasks
- `smoke_20.json` = 10 NYU test challenges + 10 Cybench tasks, all from the lowest-score slice
- `rag_sensitive_100.json` = keyword-matched Cybench tasks plus 63 NYU keyword-matched tasks selected by category quota

Model default:
- `codex/gpt-5.6-luna`

Upstream corpora:
- NYU CTF Bench: https://github.com/NYU-LLM-CTF/NYU_CTF_Bench
- Cybench: https://github.com/andyzorigin/cybench

Local clone paths:
- `benchmarks/NYU_CTF_Bench`
- `benchmarks/cybench`

Regenerate:
- `uv run python scripts/build_rag_eval_sets.py`

Run:
- `uv run python scripts/run_rag_eval.py --concurrency 1 --max-tokens 500000`

Notes:
- Keep the upstream corpora local.
- Commit the manifest JSON files, not the raw challenge archives.
