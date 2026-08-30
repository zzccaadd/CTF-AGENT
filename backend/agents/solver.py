"""Per-model solver agent — one model, one container, one challenge."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset

from backend.cost_tracker import CostTracker
from backend.deps import SolverDeps
from backend.loop_detect import LOOP_WARNING_MESSAGE, LoopDetector
from backend.models import (
    model_id_from_spec,
    provider_from_spec,
    resolve_model,
    resolve_model_settings,
    supports_vision,
)
from backend.output_types import FlagFound
from backend.prompts import ChallengeMeta, build_prompt, list_distfiles
from backend.sandbox import DockerSandbox
from backend.solver_base import CANCELLED, CORRECT_MARKERS, ERROR, FLAG_FOUND, GAVE_UP, SolverResult
from backend.tools.flag import submit_flag
from backend.tools.sandbox import (
    bash,
    check_findings,
    list_files,
    notify_coordinator,
    read_file,
    web_fetch,
    webhook_create,
    webhook_get_requests,
    write_file,
)
from backend.tools.vision import view_image
from backend.tracing import SolverTracer

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.evidence import EvidenceBoard
    from backend.submission import FlagSubmitter

logger = logging.getLogger(__name__)


@dataclass
class TracingToolset(WrapperToolset[SolverDeps]):
    """Wraps a toolset to add per-call tracing and loop detection."""

    tracer: SolverTracer = field(repr=False)
    loop_detector: LoopDetector = field(repr=False)
    step_counter: list[int] = field(repr=False)

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: RunContext[SolverDeps], tool: ToolsetTool[SolverDeps]
    ) -> Any:
        self.step_counter[0] += 1
        step = self.step_counter[0]

        self.tracer.tool_call(name, tool_args, step)
        board = ctx.deps.evidence_board
        intent_id = ctx.deps.intent_id
        if board:
            board.record(
                ctx.deps.model_spec or "solver",
                "worker",
                "tool_call",
                {"tool": name, "args": tool_args, "step": step, "intent_id": intent_id or ""},
                provenance={"source_kind": "trace", "source_excerpt": f"{name} called at step {step}"},
                dedupe_key=f"tool-call:{ctx.deps.model_spec}:{step}:{name}",
            )

        # Operational work must be tied to a blackboard intent. This keeps the
        # API-backed fallback under the same coordination contract as Codex.
        if board and not intent_id and name in {
            "bash", "read_file", "write_file", "list_files", "submit_flag",
            "web_fetch", "webhook_create", "webhook_get_requests", "view_image",
        }:
            message = "No active blackboard intent; claim a task before using operational tools."
            self.tracer.tool_result(name, message, step)
            board.record(
                ctx.deps.model_spec or "solver", "worker", "tool_result",
                {"tool": name, "result": message, "step": step, "intent_id": ""},
                provenance={"source_kind": "trace", "source_excerpt": message},
                dedupe_key=f"tool-result:{ctx.deps.model_spec}:{step}:{name}",
            )
            return message

        # Loop detection
        loop_status = self.loop_detector.check(name, tool_args)
        if loop_status == "break":
            logger.warning(f"Loop break on {name} at step {step}")
            self.tracer.event("loop_break", tool=name, step=step)
            # Inject loop warning by returning it as the tool result
            if board:
                board.record(
                    ctx.deps.model_spec or "solver", "worker", "tool_result",
                    {"tool": name, "result": LOOP_WARNING_MESSAGE, "step": step,
                     "intent_id": intent_id or ""},
                    provenance={"source_kind": "trace", "source_excerpt": LOOP_WARNING_MESSAGE},
                    dedupe_key=f"tool-result:{ctx.deps.model_spec}:{step}:{name}",
                )
            return LOOP_WARNING_MESSAGE

        result = await self.wrapped.call_tool(name, tool_args, ctx, tool)

        result_str = str(result) if result is not None else ""
        self.tracer.tool_result(name, result_str, step)
        if board:
            board.record(
                ctx.deps.model_spec or "solver",
                "worker",
                "tool_result",
                {"tool": name, "result": result_str[:2000], "step": step, "intent_id": intent_id or ""},
                provenance={"source_kind": "tool_result", "source_excerpt": result_str[:500]},
                dedupe_key=f"tool-result:{ctx.deps.model_spec}:{step}:{name}",
            )

        # Inject loop warning alongside result on "warn" level
        if loop_status == "warn":
            result = f"{result}\n\n{LOOP_WARNING_MESSAGE}" if isinstance(result, str) else result

        # Check for confirmed flag
        if name == "submit_flag" and any(m in result_str for m in CORRECT_MARKERS):
            self.tracer.event("flag_confirmed", tool=name, step=step)

        if step % 5 == 0 and ctx.deps.message_bus and isinstance(result, str):
            from backend.tools.core import do_check_findings
            findings_text = await do_check_findings(ctx.deps.message_bus, ctx.deps.model_spec)
            if findings_text and "No new findings" not in findings_text:
                result = f"{result}\n\n---\n{findings_text}"
                self.tracer.event("findings_injected", step=step)

        return result


def _build_toolset(deps: SolverDeps) -> FunctionToolset[SolverDeps]:
    """Build the raw toolset for a solver agent."""
    tools: list[Any] = [
        bash,
        read_file,
        write_file,
        list_files,
        submit_flag,
        check_findings,
        notify_coordinator,
    ]
    if deps.allow_internet:
        tools += [web_fetch, webhook_create, webhook_get_requests]
    if deps.use_vision:
        tools.append(view_image)
    return FunctionToolset(tools=tools, max_retries=4)


class Solver:
    """A single solver: one model, one container, one challenge."""

    def __init__(
        self,
        model_spec: str,
        challenge_dir: str,
        meta: ChallengeMeta,
        ctfd: FlagSubmitter,
        cost_tracker: CostTracker,
        settings: Settings,
        cancel_event: asyncio.Event | None = None,
        sandbox: DockerSandbox | None = None,
        owns_sandbox: bool | None = None,
        solver_label: str | None = None,
        evidence_board: EvidenceBoard | None = None,
    ) -> None:
        self.model_spec = model_spec
        self.model_id = model_id_from_spec(model_spec)
        self.solver_label = solver_label or model_spec
        self.challenge_dir = challenge_dir
        self.meta = meta
        self.ctfd = ctfd
        self.cost_tracker = cost_tracker
        self.settings = settings
        self.cancel_event = cancel_event or asyncio.Event()
        self._owns_sandbox = owns_sandbox if owns_sandbox is not None else (sandbox is None)
        self.evidence_board = evidence_board
        self.intent_id: str | None = None
        self._intent_lease_seconds = int(getattr(settings, "blackboard_default_worker_lease_seconds", 300))
        self._intent_heartbeat_task: asyncio.Task | None = None

        self.sandbox = sandbox or DockerSandbox(
            image=getattr(settings, "sandbox_image", "ctf-sandbox"),
            challenge_dir=challenge_dir,
            memory_limit=getattr(settings, "container_memory_limit", "4g"),
            network_mode=getattr(settings, "sandbox_network", ""),
        )
        self.use_vision = supports_vision(model_spec)
        self.deps = SolverDeps(
            sandbox=self.sandbox,
            ctfd=ctfd,
            challenge_dir=challenge_dir,
            challenge_name=meta.name,
            workspace_dir="",
            use_vision=self.use_vision,
            cost_tracker=cost_tracker,
            allow_internet=bool(getattr(settings, "allow_internet", True)),
            evidence_board=evidence_board,
        )
        self.loop_detector = LoopDetector()
        self.tracer = SolverTracer(meta.name, self.solver_label)
        self.agent_name = f"{meta.name}/{self.solver_label}"
        self._agent: Agent[SolverDeps, FlagFound] | None = None
        self._messages: list = []
        self._step_count = [0]  # mutable ref shared with TracingToolset
        self._flag: str | None = None
        self._confirmed: bool = False
        self._findings: str = ""

    async def start(self) -> None:
        """Start the sandbox and build the agent."""
        if not self.sandbox._container:
            await self.sandbox.start()
        self.deps.workspace_dir = self.sandbox.workspace_dir

        arch_result = await self.sandbox.exec("uname -m", timeout_s=10)
        container_arch = arch_result.stdout.strip() or "unknown"

        distfile_names = list_distfiles(self.challenge_dir)
        system_prompt = build_prompt(
            self.meta,
            distfile_names,
            container_arch=container_arch,
            allow_internet=bool(getattr(self.settings, "allow_internet", True)),
        )

        model = resolve_model(self.model_spec, self.settings)
        model_settings = resolve_model_settings(self.model_spec)
        raw_toolset = _build_toolset(self.deps)
        toolset = TracingToolset(
            wrapped=raw_toolset,
            tracer=self.tracer,
            loop_detector=self.loop_detector,
            step_counter=self._step_count,
        )

        self._agent = Agent(
            model,
            deps_type=SolverDeps,
            system_prompt=system_prompt,
            model_settings=model_settings,
            toolsets=[toolset],
            output_type=FlagFound,
        )

        self.tracer.event("start", challenge=self.meta.name, model=self.model_id)
        logger.info(f"[{self.agent_name}] Solver started")

    async def run_until_done_or_gave_up(self) -> SolverResult:
        """Run the solver loop until flag found, gave up, or cancelled."""
        if not self._agent:
            await self.start()
        assert self._agent is not None

        await self._claim_next_intent()
        board_context = self.evidence_board.summary() if self.evidence_board else ""
        intent_context = ""
        if self.intent_id and self.evidence_board:
            intent = next((i for i in self.evidence_board.open_intents() if i.intent_id == self.intent_id), None)
            if intent:
                intent_context = f"\nAssigned blackboard intent: {intent.goal}\nAcceptance: {intent.acceptance}\n"
        prompt = ("Solve this CTF challenge." if not self._messages else "Continue solving.")
        if board_context:
            prompt += f"\n{intent_context}\nShared blackboard:\n{board_context}"

        t0 = time.monotonic()
        try:
            from pydantic_ai.usage import UsageLimits
            result = await self._agent.run(
                prompt,
                deps=self.deps,
                message_history=self._messages if self._messages else None,
                usage_limits=UsageLimits(request_limit=None),
            )

            duration = time.monotonic() - t0
            usage = result.usage

            self.cost_tracker.record(
                self.agent_name, usage, self.model_id,
                provider_spec=provider_from_spec(self.model_spec),
                duration_seconds=duration,
            )

            agent_usage = self.cost_tracker.by_agent.get(self.agent_name)
            self.tracer.usage(
                usage.input_tokens, usage.output_tokens,
                usage.cache_read_tokens,
                agent_usage.cost_usd if agent_usage else 0.0,
            )

            self._messages = result.all_messages()

            # Trace model responses from new messages
            from pydantic_ai.messages import ModelResponse, TextPart
            for msg in result.new_messages():
                if isinstance(msg, ModelResponse):
                    text_parts = [p.content for p in msg.parts if isinstance(p, TextPart)]
                    text = " ".join(text_parts)
                    msg_usage = msg.usage
                    self.tracer.model_response(
                        text[:500], self._step_count[0],
                        input_tokens=msg_usage.input_tokens if msg_usage else 0,
                        output_tokens=msg_usage.output_tokens if msg_usage else 0,
                    )

            output = result.output
            if isinstance(output, FlagFound):
                candidate = str(output.flag or "").strip()
                if candidate:
                    self._flag = candidate
                    self._findings = f"Flag found via {output.method}: {candidate}"
                    # In dry-run mode, structured output is sufficient (can't verify via CTFd)
                    if self.deps.no_submit:
                        self._confirmed = True
                else:
                    self._findings = "Invalid flag_found output: flag is empty; continuing investigation."
            # CTFd confirmation always counts (the primary path when not in dry-run)
            if self.deps.confirmed_flag:
                self._confirmed = True
                self._flag = self._flag or self.deps.confirmed_flag

            if self._confirmed and self._flag:
                await self._finalize_intent(FLAG_FOUND)
                return self._result(FLAG_FOUND)
            await self._finalize_intent(GAVE_UP)
            return self._result(GAVE_UP)

        except asyncio.CancelledError:
            await self._finalize_intent(CANCELLED)
            return self._result(CANCELLED)
        except Exception as e:
            logger.error(f"[{self.agent_name}] Error: {e}", exc_info=True)
            self._findings = f"Error: {e}"
            self.tracer.event("error", error=str(e))
            await self._finalize_intent(ERROR)
            return self._result(ERROR)

    async def _claim_next_intent(self) -> None:
        if not self.evidence_board or self.intent_id:
            return
        max_attempts = int(getattr(self.settings, "blackboard_intent_max_attempts", 3))
        for intent in self.evidence_board.open_intents():
            claimed = self.evidence_board.claim(
                self.solver_label,
                intent.intent_id,
                lease_seconds=self._intent_lease_seconds,
                max_attempts=max_attempts,
            )
            if claimed:
                self.intent_id = claimed.intent_id
                self.deps.intent_id = claimed.intent_id
                self._intent_heartbeat_task = asyncio.create_task(self._heartbeat_intent())
                return

    async def _heartbeat_intent(self) -> None:
        try:
            while self.intent_id and not self.cancel_event.is_set():
                await asyncio.sleep(max(1, min(60, self._intent_lease_seconds // 3)))
                if self.intent_id and not self.evidence_board:
                    return
                if self.intent_id and not self.evidence_board.heartbeat(
                    self.intent_id, self.solver_label, self._intent_lease_seconds
                ):
                    self.evidence_board.record(
                        self.solver_label,
                        "worker",
                        "intent_lease_lost",
                        {"intent_id": self.intent_id},
                        provenance={"source_kind": "trace", "source_excerpt": "intent lease heartbeat rejected"},
                    )
                    self.intent_id = None
                    self.deps.intent_id = None
                    return
        except asyncio.CancelledError:
            return

    async def _finalize_intent(self, solver_status: str) -> None:
        if not self.evidence_board or not self.intent_id:
            return
        intent_id, self.intent_id = self.intent_id, None
        self.deps.intent_id = None
        if self._intent_heartbeat_task:
            self._intent_heartbeat_task.cancel()
            await asyncio.gather(self._intent_heartbeat_task, return_exceptions=True)
            self._intent_heartbeat_task = None
        terminal = "blocked" if solver_status == CANCELLED else ("failed" if solver_status == ERROR else "completed")
        self.evidence_board.complete(
            self.solver_label,
            intent_id,
            self._findings or solver_status,
            status=terminal,
        )

    def bump(self, insights: str) -> None:
        """Inject insights from siblings and prepare to resume."""
        bump_msg = ModelRequest(
            parts=[
                UserPromptPart(
                    content=(
                        "Your previous attempt did not find the flag. Here are insights "
                        "from other agents working on the same challenge:\n\n"
                        f"{insights}\n\n"
                        "Use these insights to try a different approach. "
                        "Do NOT repeat what has already been tried."
                    )
                )
            ]
        )
        self._messages.append(bump_msg)
        self.loop_detector.reset()
        self.tracer.event("bump", insights=insights[:500])
        logger.info(f"[{self.agent_name}] Bumped with sibling insights")

    def _result(self, status: str, run_steps: int | None = None, run_cost: float | None = None) -> SolverResult:
        agent_usage = self.cost_tracker.by_agent.get(self.agent_name)
        cost = agent_usage.cost_usd if agent_usage else 0.0
        self.tracer.event("finish", status=status, flag=self._flag, confirmed=self._confirmed, cost_usd=round(cost, 4))
        return SolverResult(
            flag=self._flag,
            status=status,
            findings_summary=self._findings[:2000],
            step_count=run_steps if run_steps is not None else self._step_count[0],
            cost_usd=run_cost if run_cost is not None else cost,
            log_path=self.tracer.path,
        )

    async def stop(self) -> None:
        if self._intent_heartbeat_task:
            self._intent_heartbeat_task.cancel()
            await asyncio.gather(self._intent_heartbeat_task, return_exceptions=True)
            self._intent_heartbeat_task = None
        self.tracer.event("stop", step_count=self._step_count[0])
        self.tracer.close()
        if self._owns_sandbox and self.sandbox:
            await self.sandbox.stop()
