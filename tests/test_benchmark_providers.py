from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend.benchmarks.providers import CybenchProvider, NYUProvider


@pytest.mark.asyncio
async def test_nyu_provider_stages_files_without_flag(tmp_path: Path) -> None:
    root = tmp_path / "nyu"
    source = root / "development" / "2024" / "CSAW-Quals" / "crypto" / "demo"
    source.mkdir(parents=True)
    (source / "cipher.txt").write_text("ciphertext", encoding="utf-8")
    (source / "challenge.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "category": "crypto",
                "description": "recover it",
                "files": ["cipher.txt"],
                "points": 100,
                "flag": "flag{secret}",
            }
        ),
        encoding="utf-8",
    )

    provider = NYUProvider(root)
    specs = provider.discover("development")
    prepared = await provider.prepare(specs[0], tmp_path / "staged")

    metadata = yaml.safe_load((prepared.challenge_dir / "metadata.yml").read_text())
    assert metadata["name"] == "demo"
    assert (prepared.challenge_dir / "distfiles" / "cipher.txt").read_text() == "ciphertext"
    assert "flag{secret}" not in (prepared.challenge_dir / "metadata.yml").read_text()
    assert prepared.network_mode == "none"


@pytest.mark.asyncio
async def test_cybench_provider_uses_last_subtask_as_unguided_answer(tmp_path: Path) -> None:
    root = tmp_path / "cybench"
    source = root / "benchmark" / "demo-ctf" / "crypto" / "challenge"
    metadata_dir = source / "metadata"
    challenge_dir = source / "challenge"
    metadata_dir.mkdir(parents=True)
    challenge_dir.mkdir()
    (challenge_dir / "output.txt").write_text("public data", encoding="utf-8")
    (metadata_dir / "metadata.json").write_text(
        json.dumps(
            {
                "categories": ["crypto"],
                "difficulty": "2",
                "hard_prompt": "Find the flag.",
                "target_host": "",
                "subtasks": [
                    {"question": "intermediate?", "answer": "step"},
                    {"question": "What's the flag?", "answer": "CTF{answer}"},
                ],
            }
        ),
        encoding="utf-8",
    )

    provider = CybenchProvider(root)
    specs = provider.discover("benchmark")
    prepared = await provider.prepare(specs[0], tmp_path / "staged")

    assert specs[0].expected_flags == ("CTF{answer}",)
    assert (prepared.challenge_dir / "distfiles" / "output.txt").read_text() == "public data"
    staged_text = "\n".join(
        path.read_text(errors="ignore")
        for path in prepared.challenge_dir.rglob("*")
        if path.is_file()
    )
    assert "CTF{answer}" not in staged_text
    assert prepared.network_mode == "none"
