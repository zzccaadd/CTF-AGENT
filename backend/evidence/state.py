"""Pure event-to-view folding for the Stage 1 blackboard."""

from __future__ import annotations

from collections.abc import Iterable

from backend.evidence.models import BoardSnapshot, EvidenceEvent, Intent


def _fold_intents(events: list[EvidenceEvent]) -> list[Intent]:
    intents: dict[str, Intent] = {}
    for event in events:
        if event.kind == "intent_proposed":
            intent_id = str(event.payload.get("intent_id", ""))
            if intent_id and intent_id not in intents:
                intents[intent_id] = Intent(
                    intent_id=intent_id,
                    challenge_name=event.challenge_name,
                    run_id=event.run_id,
                    goal=str(event.payload.get("goal", "")),
                    acceptance=str(event.payload.get("acceptance", "")),
                    created_event_id=event.event_id,
                )
        elif event.kind == "intent_claimed":
            intent_id = str(event.payload.get("intent_id", ""))
            current = intents.get(intent_id)
            if current:
                intents[intent_id] = Intent(
                    **{**current.__dict__, "status": "claimed", "worker_id": event.actor_id,
                       "lease_until": event.payload.get("lease_until"), "attempt": current.attempt + 1}
                )
        elif event.kind == "intent_completed":
            intent_id = str(event.payload.get("intent_id", ""))
            current = intents.get(intent_id)
            if current:
                intents[intent_id] = Intent(
                    **{**current.__dict__, "status": str(event.payload.get("status", "completed")),
                       "worker_id": None, "lease_until": None,
                       "result": str(event.payload.get("result", ""))[:2000],
                       "result_event_id": event.event_id}
                )
    return sorted(intents.values(), key=lambda intent: intent.intent_id)


def fold_events(
    challenge_name: str,
    run_id: str,
    events: Iterable[EvidenceEvent],
    intents: Iterable[Intent] | None = None,
) -> BoardSnapshot:
    ordered = sorted(events, key=lambda event: event.seq)
    folded_intents = _fold_intents(ordered) if intents is None else list(intents)
    flags = [
        event.payload.get("flag")
        for event in ordered
        if event.kind == "flag_verified" and event.payload.get("flag")
    ]
    return BoardSnapshot(
        challenge_name=challenge_name,
        run_id=run_id,
        facts=[event for event in ordered if event.kind == "fact_added"],
        hypotheses=[event for event in ordered if event.kind == "hypothesis_added"],
        dead_ends=[event for event in ordered if event.kind == "dead_end_added"],
        intents=folded_intents,
        flag=flags[0] if flags else None,
        last_seq=ordered[-1].seq if ordered else 0,
    )
