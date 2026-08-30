"""Cybench unguided adapter."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

from backend.benchmarks.models import BenchmarkChallenge, PreparedChallenge
from backend.benchmarks.providers.base import (
    BenchmarkProvider,
    ensure_internal_network,
    run_command,
    write_agent_challenge,
)


class CybenchProvider(BenchmarkProvider):
    name = "cybench"

    async def _remove_tree(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            pass
        await run_command(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{path}:/target:rw",
                self.image,
                "bash",
                "-lc",
                "chmod -R a+rwX /target",
            ],
            cwd=path.parent,
            timeout=60,
        )
        shutil.rmtree(path)

    @staticmethod
    def _is_service_init_script(path: Path) -> bool:
        if not path.exists():
            return False
        text = path.read_text(encoding="utf-8", errors="ignore")
        return any(
            marker in text
            for marker in (
                "docker-compose",
                "docker compose",
                "start_docker.sh",
            )
        )

    @staticmethod
    def _patch_legacy_debian_dockerfiles(source_dir: Path) -> None:
        for dockerfile in source_dir.rglob("Dockerfile"):
            text = dockerfile.read_text(encoding="utf-8", errors="ignore")
            if "buster" not in text or "apt update" not in text:
                continue
            if "archive.debian.org" in text or "ctf-agent-buster-archive" in text:
                continue
            lines = text.splitlines()
            insert_at = next((idx + 1 for idx, line in enumerate(lines) if line.lstrip().upper().startswith("FROM ")), 1)
            patch = [
                "RUN sed -i "
                "'s|deb.debian.org/debian-security|archive.debian.org/debian-security|g; "
                "s|security.debian.org/debian-security|archive.debian.org/debian-security|g; "
                "s|deb.debian.org/debian|archive.debian.org/debian|g; "
                "/buster-updates/d' /etc/apt/sources.list "
                "&& printf 'Acquire::Check-Valid-Until \"false\";\\n' "
                "> /etc/apt/apt.conf.d/99ctf-agent-buster-archive",
            ]
            updated = lines[:insert_at] + patch + lines[insert_at:]
            dockerfile.write_text("\n".join(updated) + "\n", encoding="utf-8")

    def discover(self, split: str = "benchmark") -> list[BenchmarkChallenge]:
        search_root = self.root / split if (self.root / split).is_dir() else self.root
        challenges = []
        for metadata_path in sorted(search_root.rglob("metadata/metadata.json")):
            data = self.load_json(metadata_path)
            source_dir = metadata_path.parent.parent
            subtasks = data.get("subtasks") or []
            final_answer = ""
            if subtasks and isinstance(subtasks[-1], dict):
                final_answer = str(subtasks[-1].get("answer") or "").strip()
            if not final_answer:
                continue

            categories = data.get("categories") or []
            category = str(categories[0]) if categories else ""
            if category == "reversing":
                category = "rev"

            challenge_id = source_dir.relative_to(search_root).as_posix()
            start_script = source_dir / "start_docker.sh"
            stop_script = source_dir / "stop_docker.sh"
            init_script = source_dir / "init_script.sh"
            service_init_script = init_script if self._is_service_init_script(init_script) else None
            compose_file = next(
                (
                    path
                    for path in (
                        source_dir / "docker-compose.yml",
                        source_dir / "docker-compose.yaml",
                        source_dir / "metadata" / "env" / "docker-compose.yml",
                        source_dir / "metadata" / "env" / "docker-compose.yaml",
                    )
                    if path.exists()
                ),
                None,
            )
            if not start_script.exists() and service_init_script:
                start_script = service_init_script
                init_script = None
            target_host = str(data.get("target_host") or "").strip()
            connection_info = target_host
            if target_host and "://" not in target_host and not target_host.startswith("nc "):
                connection_info = f"nc {target_host}" if ":" in target_host else target_host

            challenges.append(
                BenchmarkChallenge(
                    challenge_id=challenge_id,
                    provider=self.name,
                    source_dir=source_dir,
                    name=source_dir.name,
                    category=category,
                    description=str(data.get("hard_prompt") or data.get("challenging_prompt") or data.get("easy_prompt") or ""),
                    expected_flags=(final_answer,),
                    value=int(data.get("difficulty") or 0),
                    connection_info=connection_info,
                    compose_file=compose_file,
                    init_script=init_script if init_script and init_script.exists() else None,
                    start_script=start_script if start_script.exists() else None,
                    stop_script=stop_script if stop_script.exists() else None,
                    metadata=data,
                )
            )
        return challenges

    async def prepare(self, spec: BenchmarkChallenge, destination: Path) -> PreparedChallenge:
        artifact_dir = destination / "_artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        if spec.init_script:
            sanitized_source = destination / "_source"

            def ignore(path: str, names: list[str]) -> set[str]:
                current = Path(path)
                if current.name == "metadata" and "solution" in names:
                    return {"solution"}
                return set()

            shutil.copytree(spec.source_dir, sanitized_source, ignore=ignore)
            await run_command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "-v",
                    f"{sanitized_source}:/task:rw",
                    "-v",
                    f"{artifact_dir}:/output:rw",
                    "-w",
                    "/task",
                    self.image,
                    "bash",
                    "./init_script.sh",
                    "/output",
                    "false",
                ],
                cwd=destination,
                timeout=900,
            )
            await self._remove_tree(sanitized_source)
        else:
            challenge_files = spec.source_dir / "challenge"
            if challenge_files.is_dir():
                for source in challenge_files.iterdir():
                    target = artifact_dir / source.name
                    if source.is_dir():
                        shutil.copytree(source, target)
                    else:
                        shutil.copy2(source, target)

        staged_files = tuple(path for path in artifact_dir.iterdir())
        staged_spec = replace(spec, files=staged_files)
        write_agent_challenge(staged_spec, destination)
        await self._remove_tree(artifact_dir)

        project_hash = hashlib.sha256(spec.challenge_id.encode()).hexdigest()[:10]
        network_mode = "shared_net" if spec.start_script or spec.compose_file else "none"
        return PreparedChallenge(
            spec=staged_spec,
            challenge_dir=destination,
            network_mode=network_mode,
            project_name=f"ctfagent-cybench-{project_hash}",
        )

    async def start(self, prepared: PreparedChallenge) -> None:
        if prepared.spec.compose_file:
            await ensure_internal_network(prepared.network_mode)
            self._patch_legacy_debian_dockerfiles(prepared.spec.source_dir)
            await run_command(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(prepared.spec.compose_file),
                    "-p",
                    prepared.project_name,
                    "up",
                    "--build",
                    "-d",
                ],
                cwd=prepared.spec.compose_file.parent,
                timeout=1_800,
            )
            return

        script = prepared.spec.start_script
        if not script:
            return
        await ensure_internal_network(prepared.network_mode)
        self._patch_legacy_debian_dockerfiles(prepared.spec.source_dir)
        await run_command(["bash", str(script)], cwd=prepared.spec.source_dir, timeout=1_800)

    async def stop(self, prepared: PreparedChallenge) -> None:
        if prepared.spec.compose_file:
            await run_command(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(prepared.spec.compose_file),
                    "-p",
                    prepared.project_name,
                    "down",
                    "--remove-orphans",
                ],
                cwd=prepared.spec.compose_file.parent,
                timeout=300,
            )
            return

        script = prepared.spec.stop_script
        if script:
            await run_command(["bash", str(script)], cwd=prepared.spec.source_dir, timeout=300)
