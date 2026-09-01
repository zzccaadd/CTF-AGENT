"""Muteki-style coordinator planner (Stage 3 S3.2 alignment).

The coordinator is the swarm's global planner: it reads the shared blackboard
(verified facts, hypotheses, dead ends, open intents) and proposes
non-overlapping intents for workers to claim. Semantics follow
`muteki-main/muteki/solver/reason.py`:

- triggered when the blackboard's verified-fact / dead-end counts change
  (not every step);
- runs ONE Codex turn on the configured model (default gpt-5.5);
- performs an evidence audit: intents may only be built on VERIFIED facts;
  hypotheses and dead ends are context, not foundations;
- verdict state machine: explore | course_correct | complete;
- every coordinator reasoning message and plan is written to its own trace
  file (trace-coordinator-*.jsonl).

The coordinator has no sandbox and no solver tools — it only plans.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import re
from dataclasses import dataclass, field

from backend.tracing import SolverTracer

VERDICT_EXPLORE = "explore"
VERDICT_COURSE_CORRECT = "course_correct"
VERDICT_COMPLETE = "complete"

REASON_PROMPT = """You are the COORDINATOR planner of a CTF-solving swarm. Read the shared blackboard and decide the next non-overlapping intents for the workers.

EVIDENCE AUDIT (mandatory):
- Build EXPLOITATION/KEY intents ONLY on VERIFIED facts.
- With no verified facts yet, you may propose RECON/VERIFICATION intents whose
  job is to confirm or refute a hypothesis with real tool output — mark them
  "based_on_hypotheses": true and keep them observational, never conclusive.
- Hypotheses and dead ends are context for everything else.
- Do NOT propose an intent that duplicates an existing open/claimed/completed intent.
- If the flag is already confirmed or the goal is proven by verified facts, verdict must be "complete".
- verdict meanings: "explore" = keep making progress; "course_correct" = the swarm drifted, propose a new direction; "complete" = goal already satisfied.
- Intents may include using the search_knowledge tool to consult the local knowledge base when the task needs a technique/format the workers may not know.
- Do NOT read any skill files, local documentation, or the filesystem. You are a planner without tools: reply with the JSON object directly.

Reply with ONLY a JSON object:
{{"verdict": "explore|course_correct|complete", "intents": [{{"goal": "...", "rationale": "...", "based_on_hypotheses": false, "depends_on": [], "from_facts": []}}], "audit": ["one line per audit decision"]}}

Blackboard summary:
{summary}"""


@dataclass
class CoordinatorPlan:
    verdict: str = VERDICT_EXPLORE
    intents: list[dict] = field(default_factory=list)
    audit: list[str] = field(default_factory=list)
    raw: str = ""


class Coordinator:
    """One-shot Codex planner with its own trace file."""

    def __init__(self, settings, challenge_name: str, run_id: str) -> None:
        self.model = str(getattr(settings, "coordinator_model", "gpt-5.5"))
        self.turn_budget_s = int(getattr(settings, "coordinator_turn_timeout_s", 120))
        self.tracer = SolverTracer(challenge_name, "coordinator")
        self.run_id = run_id
        self._intent_index = itertools.count(1)

    def close(self) -> None:
        self.tracer.close()

    @staticmethod
    def _parse_plan(text: str) -> CoordinatorPlan:
        """Tolerantly extract the JSON plan from the model's final text."""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return CoordinatorPlan(raw=text[:500])
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return CoordinatorPlan(raw=text[:500])
        verdict = data.get("verdict", VERDICT_EXPLORE)
        if verdict not in (VERDICT_EXPLORE, VERDICT_COURSE_CORRECT, VERDICT_COMPLETE):
            verdict = VERDICT_EXPLORE
        intents = data.get("intents") or []
        intents = [
            {
                "goal": str(item.get("goal", "")).strip(),
                "rationale": str(item.get("rationale", "")).strip(),
                "depends_on": list(item.get("depends_on") or []),
                "from_facts": list(item.get("from_facts") or []),
            }
            for item in intents
            if isinstance(item, dict) and str(item.get("goal", "")).strip()
        ]
        audit = [str(item) for item in (data.get("audit") or [])]
        return CoordinatorPlan(verdict=verdict, intents=intents, audit=audit, raw=text[:2000])

    async def plan(self, board_summary: str) -> CoordinatorPlan:
        """Run one Codex turn with the reason prompt and return the parsed plan."""
        proc = await asyncio.create_subprocess_exec(
            "codex", "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        ids = itertools.count(1)
        pending: dict[int, asyncio.Future] = {}
        assistant_text: list[str] = []
        turn_done = asyncio.Event()

        async def rpc(method: str, params: dict | None = None) -> dict:
            msg_id = next(ids)
            msg: dict = {"id": msg_id, "method": method}
            if params:
                msg["params"] = params
            future = asyncio.get_running_loop().create_future()
            pending[msg_id] = future
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()
            return await asyncio.wait_for(future, 300)

        async def notify(method: str, params: dict | None = None) -> None:
            msg: dict = {"method": method}
            if params:
                msg["params"] = params
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()

        async def read_loop() -> None:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    turn_done.set()
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg_id = msg.get("id")
                if msg_id is not None and ("result" in msg or "error" in msg):
                    future = pending.pop(msg_id, None)
                    if future and not future.done():
                        if "error" in msg:
                            future.set_exception(RuntimeError(f"coordinator RPC error: {msg['error']}"))
                        else:
                            future.set_result(msg)
                    continue
                method = msg.get("method", "")
                params = msg.get("params", {})
                if method == "item/completed":
                    item = params.get("item", params)
                    if item.get("type") == "agentMessage" and item.get("text"):
                        text = item["text"]
                        phase = item.get("phase") or "message"
                        assistant_text.append(text)
                        self.tracer.event("assistant_message", phase=phase, text=text[:4000])
                elif method == "turn/completed":
                    turn_done.set()

        reader = asyncio.create_task(read_loop())
        try:
            await rpc("initialize", {
                "clientInfo": {"name": "ctf-agent-coordinator", "version": "1.0"},
                "capabilities": {"experimentalApi": True},
            })
            await notify("initialized", {})
            resp = await rpc("thread/start", {
                "model": self.model,
                "personality": "pragmatic",
                "baseInstructions": REASON_PROMPT.format(summary=board_summary[:8000]),
                "cwd": "/tmp",
                "approvalPolicy": "on-request",
                "sandbox": "read-only",
                "serviceTier": "flex",
                "dynamicTools": [],
            })
            thread_id = resp["result"]["thread"]["id"]
            await rpc("turn/start", {
                "threadId": thread_id,
                "input": [{"type": "text", "text": "Produce the plan now."}],
            })
            try:
                await asyncio.wait_for(turn_done.wait(), self.turn_budget_s)
            except TimeoutError:
                self.tracer.event("plan_failed", reason="turn_timeout")
                return CoordinatorPlan(raw="")
        finally:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except TimeoutError:
                proc.kill()
            reader.cancel()

        plan = self._parse_plan("\n".join(assistant_text))
        self.tracer.event(
            "plan",
            verdict=plan.verdict,
            intents=[intent["goal"] for intent in plan.intents],
            audit=plan.audit,
        )
        return plan

    def propose(self, board, plan: CoordinatorPlan, existing_goals: set[str]) -> list[str]:
        """Audited proposal: skip empty/duplicate intents, stamp run-scoped ids.

        Returns the ids of intents actually proposed."""
        proposed: list[str] = []
        for intent in plan.intents:
            goal = str(intent["goal"]).strip()
            if not goal or goal in existing_goals:
                continue
            intent_id = f"coord:{self.run_id}:{next(self._intent_index)}"
            board.propose(
                "coordinator",
                goal,
                acceptance="Record verified facts or a dead end, then complete the intent",
                intent_id=intent_id,
            )
            existing_goals.add(goal)
            proposed.append(intent_id)
        return proposed
