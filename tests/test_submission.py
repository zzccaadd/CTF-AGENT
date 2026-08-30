from __future__ import annotations

import pytest

from backend.submission import LocalFlagVerifier


@pytest.mark.asyncio
async def test_local_flag_verifier_accepts_only_exact_flag() -> None:
    verifier = LocalFlagVerifier("demo", ("flag{correct}",))

    wrong = await verifier.submit_flag("demo", "FLAG{correct}")
    correct = await verifier.submit_flag("demo", " flag{correct} ")
    repeated = await verifier.submit_flag("demo", "flag{correct}")

    assert wrong.status == "incorrect"
    assert correct.status == "correct"
    assert repeated.status == "already_solved"
    assert verifier.accepted_flag == "flag{correct}"
    assert verifier.submitted_flags == ["FLAG{correct}", "flag{correct}", "flag{correct}"]


@pytest.mark.asyncio
async def test_local_flag_verifier_rejects_challenge_mismatch() -> None:
    verifier = LocalFlagVerifier("expected", ("flag{ok}",))
    result = await verifier.submit_flag("other", "flag{ok}")
    assert result.status == "unknown"
    assert verifier.accepted_flag is None
