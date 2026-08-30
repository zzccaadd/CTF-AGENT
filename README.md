# CTF Agent

CTF Agent is an autonomous CTF solving system with a coordinator + solver-swarm architecture. It runs challenges inside isolated Docker sandboxes, supports multiple solver backends, and ships with a reproducible benchmark harness for comparing solver behavior across challenge sets.

## What This Project Does

- Runs CTF challenges end to end in Docker
- Lets a coordinator assign work to one or more solvers
- Keeps challenge execution isolated from the host
- Collects traces, costs, and solve outcomes
- Provides repeatable benchmark manifests for baseline and RAG-style evaluation

## Repo Layout

- `backend/` - core agent, benchmark, and sandbox logic
- `scripts/` - benchmark builders and runners
- `benchmarks/` - benchmark corpora and curated evaluation manifests
- `results/` - generated benchmark outputs
- `logs/` - solver traces and runtime logs

## Default Model

The benchmark default is `codex/gpt-5.6-luna`.

## RAG Evaluation

The curated RAG evaluation lives in `benchmarks/rag_eval/`:

- `main_100.json` - full benchmark set
- `smoke_20.json` - fast smoke set
- `rag_sensitive_100.json` - RAG-sensitive set
- `smoke_20_no_character.json` and `smoke_20_after_delulu.json` - temporary local subsets created during smoke debugging

Generate the manifests with:

```bash
uv run python scripts/build_rag_eval_sets.py
```

Run the evaluation with:

```bash
uv run python scripts/run_rag_eval.py
```

Default runner settings:

- model: `codex/gpt-5.6-luna`
- timeout: `1800`
- max tokens: `500000`
- concurrency: `1`
- solvers per swarm: `1`
- max solvers per swarm: `1`

Results are written to `results/rag_eval/`, both per provider and as a combined manifest summary.

### How Evaluation Works

1. Challenges are selected from two source corpora.
2. The selection is written into a JSON manifest.
3. The runner loads the manifest, groups challenges by provider, and discovers the matching challenge definitions locally.
4. Each challenge is prepared in an isolated temp workspace.
5. The solver runs with a fixed token budget and a single attempt.
6. A local verifier checks the submitted flag.
7. The final JSON result records solve rate, token use, cost, runtime, and trace path.

### Source Corpora

The evaluation manifests are built from these upstream datasets:

- NYU CTF Bench: https://github.com/NYU-LLM-CTF/NYU_CTF_Bench
- Cybench: https://github.com/andyzorigin/cybench

Typical local clone paths:

- `~/benchmarks/NYU_CTF_Bench`
- `~/benchmarks/cybench`

The upstream corpora stay local and do not need to be committed into this repository.
They are ignored by Git via `.gitignore` so the repo can keep only the benchmark definitions, scripts, and result summaries.

## Benchmark Manifest Summary

- `main_100.json`: 57 NYU test challenges + 43 Cybench benchmark tasks
- `smoke_20.json`: 10 NYU test challenges + 10 Cybench tasks
- `rag_sensitive_100.json`: keyword-selected challenges biased toward RAG-sensitive cases

## Notes

- Keep API keys and local runtime files out of Git.
- Use feature branches and PRs for code changes.
- Keep benchmark manifests and generation scripts versioned so results stay reproducible.

## Chinese Version

- [README.zh.md](README.zh.md)
