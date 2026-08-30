#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NYU_ROOT = ROOT / "benchmarks" / "NYU_CTF_Bench" / "test"
CYBENCH_ROOT = ROOT / "benchmarks" / "cybench" / "benchmark"
OUT_DIR = ROOT / "benchmarks" / "rag_eval"
SENSITIVE_RX = re.compile(
    r"(rsa|ecc|elliptic|pcap|http|sql|php|python|javascript|web|binary|elf|wasm|kernel|crypto|cipher|hash|compression|"
    r"image|audio|network|protocol|forensic|stego|docker|git|sqlite|xml|yaml|json|pickle|serialization|jwt|xss|ssti|"
    r"ssrf|csrf|overflow|rop|heap|format|filesystem|registry|windows|linux|gdb|radare|reverse|deobf|revers)",
    re.I,
)


def normalize_family(category: str) -> str:
    category = category.lower().strip()
    if category in {"rev", "reverse", "reversing"}:
        return "reverse"
    return category


def is_sensitive(title: str, description: str) -> bool:
    return bool(SENSITIVE_RX.search(f"{title} {description}"))


def load_nyu() -> list[dict]:
    items: list[dict] = []
    for path in sorted(NYU_ROOT.rglob("challenge.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        family = normalize_family(str(data.get("category") or ""))
        items.append(
            {
                "provider": "nyu",
                "source_provider": "nyu",
                "source_split": "test",
                "source_root": str(NYU_ROOT.relative_to(ROOT)),
                "source_path": str(path.relative_to(ROOT)),
                "challenge_id": path.parent.relative_to(NYU_ROOT).as_posix(),
                "source_category": str(data.get("category") or ""),
                "family": family,
                "name": str(data.get("name") or path.parent.name),
                "score": int(data.get("points") or data.get("initial") or 0),
                "description": str(data.get("description") or ""),
            }
        )
    return items


def load_cybench() -> list[dict]:
    items: list[dict] = []
    for path in sorted(CYBENCH_ROOT.rglob("metadata.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        source_category = str((data.get("categories") or [""])[0] or "")
        family = normalize_family(source_category)
        task_dir = path.parent.parent
        prompt = str(
            data.get("easy_prompt")
            or data.get("challenging_prompt")
            or data.get("hard_prompt")
            or ""
        )
        items.append(
            {
                "provider": "cybench",
                "source_provider": "cybench",
                "source_split": "benchmark",
                "source_root": str(CYBENCH_ROOT.relative_to(ROOT)),
                "source_path": str(path.relative_to(ROOT)),
                "challenge_id": task_dir.relative_to(CYBENCH_ROOT).as_posix(),
                "source_category": source_category,
                "family": family,
                "name": str(task_dir.name),
                "score": int(data.get("difficulty") or 0),
                "description": prompt,
            }
        )
    return items


def select_lowest(items: list[dict], quotas: dict[str, int]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[item["family"]].append(item)

    chosen: list[dict] = []
    for family, quota in quotas.items():
        subset = sorted(grouped.get(family, []), key=lambda x: (x["score"], x["challenge_id"]))
        chosen.extend(subset[:quota])
    return sorted(chosen, key=lambda x: (x["family"], x["score"], x["challenge_id"]))


def select_sensitive_nyu(items: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        if is_sensitive(item["name"], item["description"]):
            grouped[item["family"]].append(item)

    quotas = {
        "crypto": 17,
        "reverse": 12,
        "pwn": 10,
        "web": 10,
        "misc": 8,
        "forensics": 6,
    }
    chosen: list[dict] = []
    for family, quota in quotas.items():
        subset = sorted(grouped.get(family, []), key=lambda x: (-x["score"], x["challenge_id"]))
        chosen.extend(subset[:quota])
    return sorted(chosen, key=lambda x: (x["family"], -x["score"], x["challenge_id"]))


def select_sensitive_cybench(items: list[dict]) -> list[dict]:
    chosen = [item for item in items if is_sensitive(item["name"], item["description"])]
    return sorted(chosen, key=lambda x: (x["family"], x["score"], x["challenge_id"]))


def summarize(items: list[dict]) -> dict:
    by_family: dict[str, int] = defaultdict(int)
    by_provider: dict[str, int] = defaultdict(int)
    for item in items:
        by_family[item["family"]] += 1
        by_provider[item["provider"]] += 1
    return {
        "total": len(items),
        "by_family": dict(sorted(by_family.items())),
        "by_provider": dict(sorted(by_provider.items())),
    }


def write_manifest(name: str, items: list[dict], note: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "default_model": "codex/gpt-5.6-luna",
        "note": note,
        "summary": summarize(items),
        "items": items,
    }
    (OUT_DIR / f"{name}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> None:
    nyu = load_nyu()
    cybench = load_cybench()

    main_nyu = select_lowest(
        nyu,
        {
            "crypto": 10,
            "reverse": 10,
            "pwn": 10,
            "web": 10,
            "misc": 10,
            "forensics": 7,
        },
    )
    smoke_nyu = select_lowest(
        nyu,
        {
            "crypto": 2,
            "reverse": 2,
            "pwn": 2,
            "web": 2,
            "misc": 1,
            "forensics": 1,
        },
    )
    smoke_cybench = select_lowest(
        cybench,
        {
            "crypto": 2,
            "reverse": 2,
            "web": 2,
            "misc": 2,
            "pwn": 1,
            "forensics": 1,
        },
    )

    write_manifest(
        "main_100",
        sorted(main_nyu + cybench, key=lambda x: (x["provider"], x["family"], x["score"], x["challenge_id"])),
        "57 NYU test challenges plus all 43 Cybench benchmark tasks.",
    )
    write_manifest(
        "smoke_20",
        sorted(smoke_nyu + smoke_cybench, key=lambda x: (x["provider"], x["family"], x["score"], x["challenge_id"])),
        "10 NYU test challenges plus 10 Cybench benchmark tasks, all chosen from the lowest-score slice.",
    )
    sensitive_nyu = select_sensitive_nyu(nyu)
    sensitive_cybench = select_sensitive_cybench(cybench)
    write_manifest(
        "rag_sensitive_100",
        sorted(
            sensitive_nyu + sensitive_cybench,
            key=lambda x: (x["provider"], x["family"], -x["score"], x["challenge_id"]),
        ),
        "Knowledge-heavy and tool-sensitive tasks chosen to stress retrieval, protocol lookup, and exploit pattern recall.",
    )

    print("Wrote:", OUT_DIR / "main_100.json")
    print("Wrote:", OUT_DIR / "smoke_20.json")
    print("Wrote:", OUT_DIR / "rag_sensitive_100.json")


if __name__ == "__main__":
    main()
