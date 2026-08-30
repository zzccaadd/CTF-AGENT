# CTF Domain Knowledge Base

This directory is the reviewed, reusable corpus for Stage 2 RAG. It is not a
benchmark copy and must never contain flags, secrets, challenge attachments,
or unreviewed challenge-specific solutions.

## Layout

```text
knowledge/
  official/       # authoritative manuals, CWE, protocols, file formats
  reference/      # reviewed CTF techniques and domain references
  internal_notes/ # project-local sandbox, blackboard, and solver rules
  manifest.json   # corpus policy and bootstrap metadata
```

Use one Markdown document per focused topic. Put a document in the narrowest
category directory, for example `official/elf/headers.md` or
`reference/pwn/format-string.md`.

The bootstrap script adds `source_type`, relative `path`, `format`, and
content hash metadata. Add the following YAML front matter to every network-
derived note so its provenance survives indexing:

```yaml
---
source_url: https://example.org/reference
source_title: Upstream document title
source_version: "1.0"
publisher: Example publisher
license: upstream license or terms
retrieved_at: 2026-08-31
topic: binary-format
tool_name: readelf
---
```

Keep the document title and section headings explicit; the indexer preserves
section and line provenance automatically. The body should be a concise,
original summary rather than a copied upstream document.

## Allowed content

- `official`: CWE, ELF/PE, ABI, HTTP/DNS/TCP, file formats, gdb, radare2,
  pwntools, z3, and Volatility documentation.
- `reference`: reviewed explanations of crypto, pwn, reverse, web, forensics,
  and misc techniques without challenge answers.
- `internal_notes`: local execution and collaboration rules that are safe to
  expose to solver workers.

Do not add benchmark data, flags, credentials, personal data, raw challenge
files, or unreviewed writeups. If a writeup is needed for research, keep it
outside this corpus and do not index it.

## Solution patterns in reference/ (writeup-derived)

Writeups themselves stay out of the corpus, but their *generic* lessons are
welcome as `reference/<category>/<pattern>.md` cards. A pattern card:

- states a challenge type -> general method -> tools -> verification steps;
- never contains a challenge name, flag, attachment, endpoint, stack layout,
  payload bytes, or any content that only applies to one challenge;
- uses `source_title`/`publisher`/`license` front matter and intentionally
  leaves `source_url` unset so bootstrap falls back to the local file path as
  the explicit local provenance (stable content-addressed document_id).

Pattern cards are exactly what the RAG eval gates on: they must generalize
across many challenges so the solver gains reusable technique knowledge
without the evaluation sets leaking answers.

## Build

```bash
.venv/bin/python scripts/bootstrap_knowledge.py \
  --root knowledge \
  --db logs/knowledge.sqlite3
```

The command writes `logs/knowledge.manifest.json` with indexed files, hashes,
chunk counts, failures, and deleted documents.
