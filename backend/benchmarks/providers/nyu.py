"""NYU CTF Bench adapter."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from backend.benchmarks.models import BenchmarkChallenge, PreparedChallenge
from backend.benchmarks.providers.base import (
    BenchmarkProvider,
    ensure_internal_network,
    run_command,
    write_agent_challenge,
)


def _container_ids(output: str) -> list[str]:
    return [
        line.strip()
        for line in output.splitlines()
        if re.fullmatch(r"[0-9a-f]{12,64}", line.strip())
    ]


class NYUProvider(BenchmarkProvider):
    name = "nyu"

    def discover(self, split: str = "development") -> list[BenchmarkChallenge]:
        split_dir = self.root / split
        if not split_dir.is_dir():
            raise FileNotFoundError(f"NYU split not found: {split_dir}")

        challenges = []
        for metadata_path in sorted(split_dir.rglob("challenge.json")):
            data = self.load_json(metadata_path)
            source_dir = metadata_path.parent
            flag = data.get("flag")
            if not isinstance(flag, str) or not flag.strip():
                continue

            files = tuple(
                (source_dir / value).resolve()
                for value in data.get("files", [])
                if isinstance(value, str)
            )
            compose_file = next(
                (path for path in (source_dir / "docker-compose.yml", source_dir / "docker-compose.yaml") if path.exists()),
                None,
            )
            box = str(data.get("box") or "").strip()
            port = data.get("internal_port")
            connection_info = ""
            if box and port:
                if data.get("proto") == "nc" or data.get("category") not in {"web", "misc"}:
                    connection_info = f"nc {box} {port}"
                else:
                    connection_info = f"http://{box}:{port}"

            challenge_id = metadata_path.parent.relative_to(split_dir).as_posix()
            challenges.append(
                BenchmarkChallenge(
                    challenge_id=challenge_id,
                    provider=self.name,
                    source_dir=source_dir,
                    name=str(data.get("name") or source_dir.name),
                    category=str(data.get("category") or ""),
                    description=str(data.get("description") or ""),
                    expected_flags=(flag.strip(),),
                    value=int(data.get("points") or data.get("initial") or 0),
                    files=files,
                    connection_info=connection_info,
                    compose_file=compose_file,
                    metadata=data,
                )
            )
        return challenges

    async def prepare(self, spec: BenchmarkChallenge, destination: Path) -> PreparedChallenge:
        write_agent_challenge(spec, destination)
        project_hash = hashlib.sha256(spec.challenge_id.encode()).hexdigest()[:10]
        project_name = f"ctfagent-nyu-{project_hash}"
        network_mode = f"{project_name}-agent" if spec.compose_file else "none"

        return PreparedChallenge(
            spec=spec,
            challenge_dir=destination,
            network_mode=network_mode,
            project_name=project_name,
        )

    async def start(self, prepared: PreparedChallenge) -> None:
        compose_file = prepared.spec.compose_file
        if not compose_file:
            return
        compose = yaml.safe_load(compose_file.read_text(encoding="utf-8")) or {}
        for key, value in (compose.get("networks") or {}).items():
            if isinstance(value, dict) and value.get("external"):
                await ensure_internal_network(str(value.get("name") or key))
        await ensure_internal_network(prepared.network_mode)
        await run_command(
            [
                "docker",
                "compose",
                "--project-name",
                prepared.project_name,
                "-f",
                str(compose_file),
                "up",
                "-d",
                "--force-recreate",
            ],
            cwd=prepared.spec.source_dir,
            timeout=1_800,
        )

        services = compose.get("services") or {}
        box = str(prepared.spec.metadata.get("box") or "").strip()
        target_service = next(iter(services), "")
        for service_name, service in services.items():
            if not isinstance(service, dict):
                continue
            networks = service.get("networks") or {}
            network_configs = networks.values() if isinstance(networks, dict) else networks
            for network in network_configs:
                if isinstance(network, dict) and box in (network.get("aliases") or []):
                    target_service = service_name

        for service_name in services:
            container_ids = await run_command(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    prepared.project_name,
                    "-f",
                    str(compose_file),
                    "ps",
                    "-q",
                    service_name,
                ],
                cwd=prepared.spec.source_dir,
                timeout=60,
            )
            for container_id in _container_ids(container_ids):
                command = ["docker", "network", "connect", "--alias", service_name]
                if box and service_name == target_service:
                    command += ["--alias", box]
                command += [prepared.network_mode, container_id]
                await run_command(command, cwd=prepared.spec.source_dir, timeout=60)

    async def stop(self, prepared: PreparedChallenge) -> None:
        compose_file = prepared.spec.compose_file
        if not compose_file:
            return
        await run_command(
            [
                "docker",
                "compose",
                "--project-name",
                prepared.project_name,
                "-f",
                str(compose_file),
                "down",
                "--volumes",
                "--remove-orphans",
            ],
            cwd=prepared.spec.source_dir,
            timeout=300,
        )
        try:
            await run_command(
                ["docker", "network", "rm", prepared.network_mode],
                cwd=prepared.spec.source_dir,
                timeout=60,
            )
        except RuntimeError:
            pass
