"""Base provider helpers."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

import yaml

from backend.benchmarks.models import BenchmarkChallenge, PreparedChallenge


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-").lower()
    return slug or "challenge"


def write_agent_challenge(spec: BenchmarkChallenge, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    distfiles = destination / "distfiles"
    distfiles.mkdir(exist_ok=True)

    used_names: set[str] = set()
    for source in spec.files:
        if not source.exists():
            continue
        name = source.name
        if name in used_names:
            name = f"{slugify(source.parent.name)}-{name}"
        used_names.add(name)
        target = distfiles / name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

    metadata = {
        "name": spec.name,
        "category": spec.category,
        "description": spec.description,
        "value": spec.value,
        "connection_info": spec.connection_info,
        "tags": [spec.provider, spec.challenge_id],
    }
    (destination / "metadata.yml").write_text(
        yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


async def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 900,
    env: dict[str, str] | None = None,
) -> str:
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Command timed out: {' '.join(command)}") from None
    output = stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(command)}\n{output}")
    return output


async def ensure_internal_network(name: str) -> None:
    inspect = await asyncio.create_subprocess_exec(
        "docker",
        "network",
        "inspect",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if await inspect.wait() == 0:
        return
    try:
        await run_command(
            ["docker", "network", "create", "--internal", name],
            cwd=Path.cwd(),
            timeout=60,
        )
    except RuntimeError as exc:
        if "already exists" in str(exc):
            return
        raise


class BenchmarkProvider(ABC):
    name: str

    def __init__(self, root: str | Path, image: str = "ctf-sandbox") -> None:
        self.root = Path(root).expanduser().resolve()
        self.image = image

    @abstractmethod
    def discover(self, split: str) -> list[BenchmarkChallenge]: ...

    @abstractmethod
    async def prepare(self, spec: BenchmarkChallenge, destination: Path) -> PreparedChallenge: ...

    async def start(self, prepared: PreparedChallenge) -> None:
        return None

    async def stop(self, prepared: PreparedChallenge) -> None:
        return None

    @staticmethod
    def load_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))
