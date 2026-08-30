"""Flag submission interfaces shared by remote platforms and local benchmarks."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Protocol

from backend.ctfd import SubmitResult


class FlagSubmitter(Protocol):
    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult: ...


@dataclass
class LocalFlagVerifier:
    """Keep benchmark answers on the host and verify candidate flags locally."""

    challenge_name: str
    expected_flags: tuple[str, ...]
    submitted_flags: list[str] = field(default_factory=list)
    accepted_flag: str | None = None

    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult:
        candidate = flag.strip()
        self.submitted_flags.append(candidate)

        if challenge_name != self.challenge_name:
            return SubmitResult("unknown", "Challenge mismatch", "INCORRECT - challenge mismatch")

        if self.accepted_flag is not None:
            return SubmitResult(
                "already_solved",
                "Flag already accepted",
                f'ALREADY SOLVED - "{candidate}" accepted.',
            )

        if any(hmac.compare_digest(candidate, expected) for expected in self.expected_flags):
            self.accepted_flag = candidate
            return SubmitResult("correct", "Local benchmark match", f'CORRECT - "{candidate}" accepted.')

        return SubmitResult("incorrect", "Local benchmark mismatch", f'INCORRECT - "{candidate}" rejected.')
