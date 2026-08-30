"""Codex solver — drives `codex app-server` via JSON-RPC 2.0 over stdio.

Protocol shapes verified against codex-cli 0.116.0 schema:
- thread/start returns {thread: {id, ...}, ...}
- turn/start takes {threadId, input: UserInput[]}
- Dynamic tool calls arrive as item/tool/call server requests with DynamicToolCallParams
  {tool, arguments, callId, threadId, turnId}
- Client responds with DynamicToolCallResponse {contentItems: [{type, text}], success}
- Token usage via thread/tokenUsage/updated notification
- Turn completion via turn/completed notification with {threadId, turn: Turn}
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from backend.cost_tracker import CostTracker
from backend.evidence import EvidenceBoard
from backend.knowledge import KnowledgeService
from backend.loop_detect import LoopDetector
from backend.models import model_id_from_spec, supports_vision
from backend.output_types import solver_output_json_schema
from backend.prompts import ChallengeMeta, build_prompt, list_distfiles
from backend.sandbox import DockerSandbox
from backend.solver_base import CANCELLED, ERROR, FLAG_FOUND, GAVE_UP, QUOTA_ERROR, SolverResult
from backend.tools.core import (
    do_bash,
    do_list_files,
    do_read_file,
    do_view_image,
    do_web_fetch,
    do_webhook_create,
    do_webhook_get_requests,
    do_write_file,
)
from backend.tracing import SolverTracer

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.submission import FlagSubmitter

logger = logging.getLogger(__name__)

_rpc_counter = itertools.count(1)

# Per-model reasoning effort (only for models that support it)
REASONING_EFFORT: dict[str, str] = {
    "gpt-5.3-codex": "xhigh",
}

TRANSIENT_TURN_ERROR_MARKERS = (
    "503",
    "service unavailable",
    "temporarily unavailable",
    "overloaded",
    "bad gateway",
    "gateway timeout",
    "upstream",
    "timeout",
)


def _next_id() -> int:
    return next(_rpc_counter)


# DynamicToolSpec[] for thread/start
SANDBOX_TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command in the Docker sandbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the sandbox container.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "write_file",
        "description": "Write a file into the sandbox container.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    },
    {
        "name": "list_files",
        "description": "List files in a directory in the sandbox.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "default": "/challenge/distfiles"}}},
    },
    {
        "name": "submit_flag",
        "description": "Submit a flag to CTFd. Returns CORRECT, ALREADY SOLVED, or INCORRECT.",
        "inputSchema": {"type": "object", "properties": {"flag": {"type": "string"}}, "required": ["flag"]},
    },
    {
        "name": "web_fetch",
        "description": "Fetch a URL from the host network.",
        "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "method": {"type": "string", "default": "GET"}, "body": {"type": "string", "default": ""}}, "required": ["url"]},
    },
    {
        "name": "webhook_create",
        "description": "Create a webhook.site token for out-of-band HTTP callbacks (XSS, SSRF, bot challenges).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "webhook_get_requests",
        "description": "Retrieve HTTP requests received by a webhook.site token.",
        "inputSchema": {"type": "object", "properties": {"uuid": {"type": "string"}}, "required": ["uuid"]},
    },
    {
        "name": "view_image",
        "description": "View an image file from the sandbox for visual/steg analysis.",
        "inputSchema": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]},
    },
    {
        "name": "notify_coordinator",
        "description": "Send a strategic message to the coordinator (e.g. flag format discovery, shared vulnerability, request for help).",
        "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
    },
    {
        "name": "blackboard_summary",
        "description": "Read the current shared blackboard summary for this challenge.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "blackboard_intents",
        "description": "List active shared-blackboard intents and their owners.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "blackboard_claim",
        "description": "Claim one open shared-blackboard intent before doing work.",
        "inputSchema": {"type": "object", "properties": {"intent_id": {"type": "string"}}, "required": ["intent_id"]},
    },
    {
        "name": "blackboard_complete",
        "description": "Complete the currently claimed intent with a result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "status": {"type": "string", "enum": ["completed", "failed", "blocked"]},
            },
            "required": ["result"],
        },
    },
    {
        "name": "blackboard_fact",
        "description": "Record a concise fact observed in real tool output.",
        "inputSchema": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]},
    },
    {
        "name": "blackboard_hypothesis",
        "description": "Record an unverified hypothesis for other workers.",
        "inputSchema": {"type": "object", "properties": {"hypothesis": {"type": "string"}}, "required": ["hypothesis"]},
    },
    {
        "name": "blackboard_dead_end",
        "description": "Record a route that real testing ruled out.",
        "inputSchema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    },
    {
        "name": "search_knowledge",
        "description": "Search the local reviewed knowledge base. Returns source and line provenance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "source_type": {"type": "string"},
                "metadata": {"type": "object"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
    },
]

INTERNET_TOOL_NAMES = {"web_fetch", "webhook_create", "webhook_get_requests"}


def sandbox_tools(allow_internet: bool, knowledge_enabled: bool = True) -> list[dict]:
    if allow_internet:
        tools = list(SANDBOX_TOOLS)
    else:
        tools = [tool for tool in SANDBOX_TOOLS if tool["name"] not in INTERNET_TOOL_NAMES]
    if not knowledge_enabled:
        tools = [tool for tool in tools if tool["name"] != "search_knowledge"]
    return tools


class CodexSolver:
    """Codex solver speaking the actual app-server JSON-RPC 2.0 protocol."""

    def __init__(
        self,
        model_spec: str,
        challenge_dir: str,
        meta: ChallengeMeta,
        ctfd: FlagSubmitter,
        cost_tracker: CostTracker,
        settings: Settings,
        cancel_event: asyncio.Event | None = None,
        no_submit: bool = False,
        submit_fn=None,
        message_bus=None,
        notify_coordinator=None,
        solver_label: str | None = None,
        evidence_board: EvidenceBoard | None = None,
    ) -> None:
        self.model_spec = model_spec
        self.model_id = model_id_from_spec(model_spec)
        self.solver_label = solver_label or model_spec
        self.evidence_board = evidence_board
        self.intent_id: str | None = None
        self._intent_goal = ""
        self._intent_acceptance = ""
        self.challenge_dir = challenge_dir
        self.meta = meta
        self.message_bus = message_bus
        self.notify_coordinator = notify_coordinator
        self.ctfd = ctfd
        self.cost_tracker = cost_tracker
        self.settings = settings
        self.cancel_event = cancel_event or asyncio.Event()
        self.no_submit = no_submit
        self.submit_fn = submit_fn
        self.allow_internet = bool(getattr(settings, "allow_internet", True))
        self.knowledge_enabled = bool(getattr(settings, "knowledge_enabled", True))
        self.max_tokens = int(getattr(settings, "max_tokens_per_challenge", 0) or 0)
        self._dynamic_tools = sandbox_tools(self.allow_internet, self.knowledge_enabled)
        self.knowledge_service = KnowledgeService.from_path(
            getattr(settings, "knowledge_db_path", "logs/knowledge.sqlite3"),
            max_chars=int(getattr(settings, "knowledge_max_chars", 8_000)),
            timeout_ms=int(getattr(settings, "knowledge_query_timeout_ms", 200)),
        ) if self.knowledge_enabled else None
        self._knowledge_queries = 0
        self._knowledge_hits = 0
        self._knowledge_chars = 0

        self.sandbox = DockerSandbox(
            image=getattr(settings, "sandbox_image", "ctf-sandbox"),
            challenge_dir=challenge_dir,
            memory_limit=getattr(settings, "container_memory_limit", "4g"),
            network_mode=getattr(settings, "sandbox_network", ""),
        )
        self.use_vision = supports_vision(model_spec)
        self.loop_detector = LoopDetector()
        self.tracer = SolverTracer(meta.name, self.solver_label)
        self.agent_name = f"{meta.name}/{self.solver_label}"

        self._proc: asyncio.subprocess.Process | None = None
        self._thread_id: str | None = None
        self._step_count = 0
        self._flag: str | None = None
        self._confirmed = False
        self._findings = ""
        self._last_tool_output = ""
        self._last_tool_was_external = False
        self._cost_usd = 0.0
        self._bump_insights: str | None = None
        self._structured_output: dict | None = None
        self._turn_error: str | None = None
        self._compact_requested = False
        self._pending_responses: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._intent_heartbeat_task: asyncio.Task | None = None
        self._intent_lease_seconds = 300
        self._turn_done: asyncio.Event = asyncio.Event()
        self._total_tokens = 0
        self._token_budget_exhausted = False

    async def start(self) -> None:
        await self.sandbox.start()

        arch_result = await self.sandbox.exec("uname -m", timeout_s=10)
        container_arch = arch_result.stdout.strip() or "unknown"

        distfile_names = list_distfiles(self.challenge_dir)
        system_prompt = build_prompt(
            self.meta, distfile_names, container_arch=container_arch,
            has_named_tools=True,
            allow_internet=self.allow_internet,
        )

        self._proc = await asyncio.create_subprocess_exec(
            "codex", "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        self._reader_task = asyncio.create_task(self._read_loop())

        # Initialize handshake: send initialize request, then initialized notification
        await self._rpc("initialize", {
            "clientInfo": {"name": "ctf-agent", "version": "2.0.0"},
            "capabilities": {"experimentalApi": True},
        })
        await self._send_notification("initialized", {})

        # thread/start — personality is enum, system prompt in baseInstructions
        # Prepend sandbox path reminder to prevent models from using host paths
        tool_names = [t["name"] for t in self._dynamic_tools]
        sandbox_preamble = (
            "IMPORTANT: You are running inside a Docker sandbox. "
            "All files are under /challenge/ — distfiles at /challenge/distfiles/, "
            "workspace at /challenge/workspace/. Do NOT use any paths outside /challenge/. "
            f"Your tools: {', '.join(tool_names)}. Use these for ALL operations.\n\n"
        )
        thread_params = {
            "model": self.model_id,
            "personality": "pragmatic",
            "baseInstructions": sandbox_preamble + system_prompt,
            "cwd": "/challenge",
            "approvalPolicy": "on-request",
            "sandbox": "read-only",
            "serviceTier": "flex",
            "dynamicTools": self._dynamic_tools,
        }
        # Reasoning effort for models that support it
        reasoning = REASONING_EFFORT.get(self.model_id)
        if reasoning:
            thread_params["reasoningEffort"] = reasoning
        resp = await self._rpc("thread/start", thread_params)
        # ThreadStartResponse: result.thread.id
        self._thread_id = resp.get("result", {}).get("thread", {}).get("id", "")

        self.tracer.event("start", challenge=self.meta.name, model=self.model_id)
        logger.info(f"[{self.agent_name}] Codex solver started (thread={self._thread_id})")

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        assert self._proc and self._proc.stdin
        msg_id = _next_id()
        msg: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending_responses[msg_id] = future

        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout=300)
        finally:
            self._pending_responses.pop(msg_id, None)

    async def _respond_to_request(self, request_id: int, result: Any) -> None:
        """Send a JSON-RPC response to a server request (e.g. item/tool/call)."""
        assert self._proc and self._proc.stdin
        resp = {"id": request_id, "result": result}
        self._proc.stdin.write((json.dumps(resp) + "\n").encode())
        await self._proc.stdin.drain()

    async def _send_notification(self, method: str, params: dict | None = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        assert self._proc and self._proc.stdin
        msg: dict[str, Any] = {"method": method}
        if params:
            msg["params"] = params
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()

    @staticmethod
    def _is_transient_turn_error(error_text: str) -> bool:
        lower = error_text.lower()
        return any(marker in lower for marker in TRANSIENT_TURN_ERROR_MARKERS)

    async def _read_loop(self) -> None:
        """Read JSON-RPC messages: responses, notifications, and server requests."""
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                self._turn_done.set()
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_id = msg.get("id")
            if msg_id is not None and ("result" in msg or "error" in msg):
                future = self._pending_responses.pop(msg_id, None)
                if future and not future.done():
                    if "error" in msg:
                        err = msg["error"]
                        logger.error(f"[{self.agent_name}] RPC error: {err}")
                        future.set_exception(RuntimeError(f"Codex RPC error: {err}"))
                    else:
                        future.set_result(msg)
                continue

            method = msg.get("method", "")
            params = msg.get("params", {})

            # Server request: dynamic tool call
            if method == "item/tool/call" and msg_id is not None:
                await self._handle_tool_call(msg_id, params)

            # Notification: item completed — assistant text arrives here
            elif method == "item/completed":
                item = params.get("item", params)
                if item.get("type") == "agentMessage":
                    text = item.get("text", "")
                    phase = item.get("phase")  # "commentary" | "final_answer" | null
                    if text:
                        self._findings = text[:2000]
                        if phase != "commentary" and text.lstrip()[:1] == "{":
                            try:
                                parsed = json.loads(text)
                                if isinstance(parsed, dict) and "type" in parsed:
                                    self._structured_output = parsed
                            except (json.JSONDecodeError, ValueError):
                                pass

            # Notification: turn completed — signals the turn is done
            elif method == "turn/completed":
                turn = params.get("turn", {})
                status = turn.get("status", "")
                if status == "failed":
                    error = turn.get("error", {})
                    if isinstance(error, dict):
                        # Include all error fields for robust quota classification
                        parts = [error.get("message", "unknown error")]
                        codex_info = error.get("codexErrorInfo", {})
                        if isinstance(codex_info, dict):
                            parts.append(str(codex_info))
                        additional = error.get("additionalDetails")
                        if additional:
                            parts.append(str(additional))
                        error_msg = " | ".join(parts)
                    else:
                        error_msg = str(error)
                    self._turn_error = error_msg
                    logger.error(f"[{self.agent_name}] Turn failed: {error_msg}")
                    self.tracer.event("turn_failed", error=error_msg, step=self._step_count)
                    self._findings = f"Turn failed: {error_msg}"
                    self._structured_output = None
                else:
                    self._turn_error = None
                self._turn_done.set()

            # Notification: token usage updated
            # params: {threadId, turnId, tokenUsage: {last: TokenUsageBreakdown, total: TokenUsageBreakdown}}
            elif method == "thread/tokenUsage/updated":
                token_usage = params.get("tokenUsage", {})
                last = token_usage.get("last", {})
                total = token_usage.get("total", {})

                # Proactive compaction at 70% context window (only for small-context models like spark)
                context_window = token_usage.get("modelContextWindow")
                total_tokens = total.get("totalTokens", 0)
                self._total_tokens = int(total_tokens or 0)
                if (
                    self.max_tokens
                    and self._total_tokens >= self.max_tokens
                    and not self._token_budget_exhausted
                ):
                    self._token_budget_exhausted = True
                    logger.warning(
                        "[%s] Token budget exhausted (%d/%d)",
                        self.agent_name,
                        self._total_tokens,
                        self.max_tokens,
                    )
                    self.tracer.event(
                        "token_budget_exhausted",
                        tokens=self._total_tokens,
                        limit=self.max_tokens,
                    )
                    turn_id = params.get("turnId")
                    if turn_id:
                        asyncio.create_task(self._interrupt_turn(turn_id))
                if (
                    context_window
                    and context_window < 200_000
                    and total_tokens > context_window * 0.7
                    and not self._compact_requested
                ):
                    self._compact_requested = True
                    logger.info(f"[{self.agent_name}] Requesting compaction ({total_tokens}/{context_window} tokens)")
                    asyncio.create_task(self._request_compaction(total_tokens, context_window))

                self.cost_tracker.record_tokens(
                    self.agent_name, self.model_id,
                    input_tokens=last.get("inputTokens", 0),
                    output_tokens=last.get("outputTokens", 0),
                    cache_read_tokens=last.get("cachedInputTokens", 0),
                    provider_spec="codex",
                )
                agent_usage = self.cost_tracker.by_agent.get(self.agent_name)
                self._cost_usd = agent_usage.cost_usd if agent_usage else 0.0
                self.tracer.usage(
                    total.get("inputTokens", 0),
                    total.get("outputTokens", 0),
                    total.get("cachedInputTokens", 0),
                    self._cost_usd,
                )

    async def _interrupt_turn(self, turn_id: str) -> None:
        try:
            await self._rpc(
                "turn/interrupt",
                {"threadId": self._thread_id, "turnId": turn_id},
            )
        except Exception as e:
            logger.warning("[%s] Turn interrupt failed: %s", self.agent_name, e)
        finally:
            self.cancel_event.set()

    async def _request_compaction(self, total_tokens: int, context_window: int) -> None:
        try:
            await self._rpc("thread/compact/start", {"threadId": self._thread_id})
            self.tracer.event("compact_requested", tokens=total_tokens, window=context_window)
        except Exception as e:
            logger.warning("[%s] Compaction request failed: %s", self.agent_name, e)

    async def _handle_tool_call(self, request_id: int, params: dict) -> None:
        """Handle item/tool/call server request. Params are DynamicToolCallParams."""
        tool_name = params.get("tool", "")
        try:
            args = params.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
        except Exception:
            args = {}

        self._step_count += 1
        self.tracer.tool_call(tool_name, args, self._step_count)
        if self.evidence_board:
            event_args = {
                key: (value[:2000] if isinstance(value, str) else value)
                for key, value in args.items()
            }
            self.evidence_board.record(
                self.solver_label,
                "worker",
                "tool_call",
                {"tool": tool_name, "args": event_args, "step": self._step_count, "intent_id": self.intent_id or ""},
                provenance={"source_kind": "trace", "trace_path": self.tracer.path, "trace_event_index": self._step_count},
                dedupe_key=f"tool-call:{self.meta.name}:{self.evidence_board.run_id}:{self.solver_label}:{self._step_count}",
            )

        loop_status = self.loop_detector.check(tool_name, args)
        success = True
        if loop_status == "break":
            self.tracer.event("loop_break", tool=tool_name, step=self._step_count)
            result = "Loop detected — try a completely different approach."
        else:
            try:
                result = await self._exec_tool(tool_name, args)
            except Exception as exc:
                logger.exception("[%s] Tool %s failed", self.agent_name, tool_name)
                result = f"Tool error: {exc}"
                success = False
            if loop_status == "warn" and isinstance(result, str):
                from backend.loop_detect import LOOP_WARNING_MESSAGE
                result = f"{result}\n\n{LOOP_WARNING_MESSAGE}"

        # Build content items — handle image tuples from view_image
        if isinstance(result, tuple):
            image_bytes, mime_type = result
            data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
            content_items = [{"type": "inputImage", "imageUrl": data_url}]
            image_summary = f"image:{mime_type}:{len(image_bytes)}b"
            self._last_tool_output = image_summary
            self._last_tool_was_external = True
            self.tracer.tool_result(tool_name, image_summary, self._step_count)
            if self.evidence_board:
                self.evidence_board.record(
                    self.solver_label,
                    "worker",
                    "tool_result",
                    {"tool": tool_name, "step": self._step_count, "result": image_summary, "intent_id": self.intent_id or ""},
                    provenance={"source_kind": "trace", "trace_path": self.tracer.path, "trace_event_index": self._step_count},
                    dedupe_key=f"tool:{self.meta.name}:{self.evidence_board.run_id}:{self.solver_label}:{self._step_count}",
                )
        else:
            result_text = str(result)
            self._last_tool_output = result_text
            self._last_tool_was_external = tool_name not in {
                "blackboard_summary", "blackboard_intents", "blackboard_claim", "blackboard_complete",
                "blackboard_fact", "blackboard_hypothesis", "blackboard_dead_end",
            }
            self.tracer.tool_result(tool_name, result_text[:500], self._step_count)
            if self.evidence_board:
                self.evidence_board.record(
                    self.solver_label,
                    "worker",
                    "tool_result",
                    {"tool": tool_name, "step": self._step_count, "result": result_text[:2000], "intent_id": self.intent_id or ""},
                    provenance={"source_kind": "trace", "trace_path": self.tracer.path, "trace_event_index": self._step_count},
                    dedupe_key=f"tool:{self.meta.name}:{self.evidence_board.run_id if self.evidence_board else self.tracer.path}:{self.solver_label}:{self._step_count}",
                )

            if self._step_count % 5 == 0 and self.message_bus:
                from backend.tools.core import do_check_findings
                findings = await do_check_findings(self.message_bus, self.solver_label)
                if findings and "No new findings" not in findings:
                    result_text = f"{result_text}\n\n---\n{findings}"

            content_items = [{"type": "inputText", "text": result_text}]

        await self._respond_to_request(request_id, {
            "contentItems": content_items,
            "success": success,
        })

    async def _exec_tool(self, name: str, args: dict) -> str | tuple[bytes, str]:
        if name == "search_knowledge":
            if not self.knowledge_service:
                return "Knowledge search is disabled for this run."
            self._knowledge_queries += 1
            results = self.knowledge_service.search(
                str(args.get("query", "")),
                source_type=args.get("source_type"),
                metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
                top_k=args.get("top_k", getattr(self.settings, "knowledge_top_k", 5)),
            )
            self._knowledge_hits += len(results)
            self._knowledge_chars += sum(len(result.text) for result in results)
            diagnostic = self.knowledge_service.last_diagnostic
            self.tracer.event(
                "knowledge_searched",
                query_hash=diagnostic.get("query_hash", ""),
                hit_count=len(results),
                returned_chars=sum(len(result.text) for result in results),
                status=diagnostic.get("status", "unknown"),
            )
            if self.evidence_board:
                self.evidence_board.record(
                    self.solver_label,
                    "worker",
                    "knowledge_searched",
                    {"query_hash": diagnostic.get("query_hash", ""), "hit_count": len(results), "step": self._step_count, "intent_id": self.intent_id or ""},
                    provenance={
                        "source_kind": "knowledge",
                        "query_hash": diagnostic.get("query_hash", ""),
                        "results": [result.provenance for result in results],
                    },
                    dedupe_key=f"knowledge:{self.meta.name}:{self.evidence_board.run_id}:{self.solver_label}:{self._step_count}",
                )
            if not results:
                status = diagnostic.get("status", "empty")
                return f"Knowledge search returned no usable results ({status}). Continue with sandbox analysis."
            return json.dumps(
                {"results": [result.__dict__ for result in results], "diagnostic": diagnostic},
                ensure_ascii=False,
            )
        if name == "blackboard_summary":
            return self.evidence_board.summary() if self.evidence_board else "No shared blackboard available."
        elif name == "blackboard_intents":
            if not self.evidence_board:
                return "No shared blackboard available."
            return json.dumps(
                [intent.__dict__ for intent in self.evidence_board.list_open_intents()],
                ensure_ascii=False,
                indent=2,
            )
        elif name == "blackboard_claim":
            if not self.evidence_board:
                return "No shared blackboard available."
            requested = str(args.get("intent_id", ""))
            if self.intent_id and requested != self.intent_id:
                return f"Already assigned to intent {self.intent_id}. Complete it before claiming another."
            claimed = self.evidence_board.claim(
                self.solver_label,
                requested,
                int(getattr(self.settings, "blackboard_default_worker_lease_seconds", 300)),
                int(getattr(self.settings, "blackboard_intent_max_attempts", 3)),
            )
            if not claimed:
                return "Intent is unavailable or has reached its attempt limit."
            self.intent_id = claimed.intent_id
            self._intent_goal = claimed.goal
            self._intent_acceptance = claimed.acceptance
            if not self._intent_heartbeat_task:
                self._intent_heartbeat_task = asyncio.create_task(self._intent_heartbeat())
            return json.dumps(claimed.__dict__, ensure_ascii=False)
        elif name == "blackboard_complete":
            if not self.evidence_board or not self.intent_id:
                return "No intent is currently claimed."
            status = self._normalize_intent_status(args.get("status", "completed"))
            result = str(args.get("result", ""))[:2000]
            completed_id = self.intent_id
            self._complete_current_intent(result, status=status)
            return f"Completed intent {completed_id} with status {status}."
        elif name == "blackboard_fact":
            if not self.evidence_board:
                return "No shared blackboard available."
            if not self.intent_id:
                return "No intent is claimed. Claim an intent before recording evidence."
            fact = str(args.get("fact", ""))[:2000]
            verified = bool(self._last_tool_was_external and fact and fact in self._last_tool_output)
            event = self.evidence_board.add_fact(
                self.solver_label,
                fact,
                verified=verified,
                provenance={
                    "source_kind": "trace" if verified else "worker_explicit",
                    "trace_path": self.tracer.path,
                    "source_excerpt": self._last_tool_output[:500],
                },
                intent_id=self.intent_id,
            )
            label = "verified fact" if verified else "unverified candidate"
            return f"Recorded {label} event {event.event_id}."
        elif name == "blackboard_hypothesis":
            if not self.evidence_board:
                return "No shared blackboard available."
            if not self.intent_id:
                return "No intent is claimed. Claim an intent before recording a hypothesis."
            event = self.evidence_board.add_hypothesis(
                self.solver_label, str(args.get("hypothesis", ""))[:2000], intent_id=self.intent_id
            )
            return f"Recorded hypothesis event {event.event_id}."
        elif name == "blackboard_dead_end":
            if not self.evidence_board:
                return "No shared blackboard available."
            if not self.intent_id:
                return "No intent is claimed. Claim an intent before recording a dead end."
            event = self.evidence_board.add_dead_end(
                self.solver_label, str(args.get("reason", ""))[:2000], intent_id=self.intent_id
            )
            return f"Recorded dead-end event {event.event_id}."
        if self.evidence_board and not self.intent_id and name in {
            "bash", "read_file", "write_file", "list_files", "submit_flag",
            "web_fetch", "webhook_create", "webhook_get_requests", "view_image",
        }:
            return "No intent is claimed. Claim an intent before using solver tools."
        if name == "bash":
            return await do_bash(self.sandbox, args.get("command", ""), args.get("timeout_seconds", 60))
        elif name == "read_file":
            return str(await do_read_file(self.sandbox, args.get("path", "")))
        elif name == "write_file":
            return await do_write_file(self.sandbox, args.get("path", ""), args.get("content", ""))
        elif name == "list_files":
            return await do_list_files(self.sandbox, args.get("path", "/challenge/distfiles"))
        elif name == "submit_flag":
            flag = str(args.get("flag", "") or "")
            candidate = flag.strip()
            if self.no_submit:
                return f'DRY RUN — would submit "{candidate}"'
            if self.submit_fn:
                display, is_confirmed = await self.submit_fn(flag)
            else:
                from backend.tools.core import do_submit_flag
                display, is_confirmed = await do_submit_flag(self.ctfd, self.meta.name, flag)
            if is_confirmed:
                self._confirmed = True
                self._flag = candidate
            return display
        elif name == "web_fetch":
            if not self.allow_internet:
                return "Internet access is disabled for this benchmark."
            return await do_web_fetch(args.get("url", ""), args.get("method", "GET"), args.get("body", ""))
        elif name == "webhook_create":
            if not self.allow_internet:
                return "Internet access is disabled for this benchmark."
            return await do_webhook_create()
        elif name == "webhook_get_requests":
            if not self.allow_internet:
                return "Internet access is disabled for this benchmark."
            return await do_webhook_get_requests(args.get("uuid", ""))
        elif name == "view_image":
            return await do_view_image(self.sandbox, args.get("filename", ""), use_vision=self.use_vision)
        elif name == "notify_coordinator":
            if self.notify_coordinator:
                await self.notify_coordinator(args.get("message", ""))
                return "Message sent to coordinator."
            return "No coordinator connected."
        return f"Unknown tool: {name}"

    def _claim_next_intent(self) -> str:
        if not self.evidence_board:
            return ""
        if self.intent_id:
            return self.intent_id
        for intent in self.evidence_board.open_intents():
            claimed = self.evidence_board.claim(
                self.solver_label,
                intent.intent_id,
                int(getattr(self.settings, "blackboard_default_worker_lease_seconds", 300)),
                int(getattr(self.settings, "blackboard_intent_max_attempts", 3)),
            )
            if claimed:
                self.intent_id = claimed.intent_id
                self._intent_goal = claimed.goal
                self._intent_acceptance = claimed.acceptance
                self._intent_lease_seconds = int(
                    getattr(self.settings, "blackboard_default_worker_lease_seconds", 300)
                )
                self._intent_heartbeat_task = asyncio.create_task(self._intent_heartbeat())
                return self.intent_id
        return ""

    async def _intent_heartbeat(self) -> None:
        """Keep a claimed intent leased while a long Codex turn is running."""
        while self.evidence_board and self.intent_id:
            try:
                await asyncio.sleep(max(1, min(60, self._intent_lease_seconds // 3)))
            except asyncio.CancelledError:
                return
            if self.intent_id:
                renewed = self.evidence_board.heartbeat(
                    intent_id=self.intent_id,
                    worker_id=self.solver_label,
                    lease_seconds=self._intent_lease_seconds,
                )
                if not renewed:
                    self.evidence_board.record(
                        self.solver_label,
                        "worker",
                        "intent_lease_lost",
                        {"intent_id": self.intent_id},
                        provenance={"source_kind": "trace", "source_excerpt": "intent lease heartbeat rejected"},
                    )
                    self.intent_id = None
                    self._intent_goal = ""
                    self._intent_acceptance = ""
                    return

    def _complete_current_intent(self, result: str, status: str = "completed") -> None:
        if self.evidence_board and self.intent_id:
            self.evidence_board.complete(
                self.solver_label,
                self.intent_id,
                result,
                status=self._normalize_intent_status(status),
            )
            self.intent_id = None
            self._intent_goal = ""
            self._intent_acceptance = ""
            if self._intent_heartbeat_task:
                self._intent_heartbeat_task.cancel()
                self._intent_heartbeat_task = None

    @staticmethod
    def _normalize_intent_status(status: object) -> str:
        """Keep model/tool aliases from violating the persisted intent contract."""
        normalized = str(status or "completed").strip().lower()
        aliases = {
            "done": "completed",
            "complete": "completed",
            "success": "completed",
            "succeeded": "completed",
            "error": "failed",
            "gave_up": "blocked",
            "give_up": "blocked",
        }
        return aliases.get(normalized, normalized if normalized in {"completed", "failed", "blocked"} else "failed")

    async def run_until_done_or_gave_up(self) -> SolverResult:
        if not self._proc:
            await self.start()
        assert self._thread_id

        t0 = time.monotonic()
        intent_id = self._claim_next_intent() if self.evidence_board else ""
        if self.evidence_board and not intent_id:
            return self._result(GAVE_UP)
        task_context = ""
        if self.evidence_board:
            board_context = self.evidence_board.summary()
            task_context = f"\n\nYour assigned shared-blackboard task (intent {intent_id}): {self._intent_goal}\n"
            task_context += f"Acceptance: {self._intent_acceptance}\n"
            task_context += f"\nCurrent blackboard:\n{board_context}\n"
        if self._bump_insights:
            prompt_text = (
                "Your previous attempt did not find the flag. "
                f"Insights from other agents:\n\n{self._bump_insights}\n\n"
                "Try a different approach."
            )
            self._bump_insights = None
        elif self._step_count == 0:
            prompt_text = (
                "Work only on your assigned intent. Use the blackboard tools to record facts, hypotheses, and dead ends."
                if self.evidence_board else "Solve this CTF challenge."
            )
        else:
            prompt_text = (
                "Continue your assigned intent and record the result on the blackboard."
                if self.evidence_board else "Continue solving."
            )
        prompt_text += task_context

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self._turn_done.clear()
                self._structured_output = None
                self._turn_error = None
                await self._rpc("turn/start", {
                    "threadId": self._thread_id,
                    "input": [{"type": "text", "text": prompt_text}],
                    "outputSchema": solver_output_json_schema(),
                })

                await self._turn_done.wait()

                duration = time.monotonic() - t0
                self.tracer.event("turn_complete", duration=round(duration, 1), steps=self._step_count)

                # A confirmed flag wins over token-budget/error/cancel branches:
                # the same turn may hit the token cap right after submit_flag.
                if self._confirmed and self._flag:
                    self._complete_current_intent("flag verified", "completed")
                    return self._result(FLAG_FOUND)

                if self._token_budget_exhausted:
                    self._findings = f"Token budget exhausted at {self._total_tokens} tokens."
                    self._complete_current_intent(self._findings, "blocked")
                    return self._result(CANCELLED)

                if self._turn_error:
                    err = self._turn_error.lower()
                    # Context overflow is terminal — don't fallback, just error
                    if "context_length" in err or "context window" in err:
                        self._findings = f"Turn failed: {self._turn_error}"
                        self._complete_current_intent(self._findings, "failed")
                        return self._result(ERROR)
                    if self._is_transient_turn_error(err):
                        if attempt < max_attempts:
                            delay = min(2 ** (attempt - 1), 8)
                            logger.warning(
                                "[%s] Transient turn error on attempt %d/%d: %s; retrying in %ds",
                                self.agent_name,
                                attempt,
                                max_attempts,
                                self._turn_error,
                                delay,
                            )
                            self.tracer.event(
                                "turn_retry",
                                attempt=attempt,
                                max_attempts=max_attempts,
                                error=self._turn_error,
                            )
                            await asyncio.sleep(delay)
                            continue
                        self._findings = f"Turn failed: {self._turn_error}"
                        self._complete_current_intent(self._findings, "failed")
                        return self._result(ERROR)
                    if any(k in err for k in ("quota", "rate", "capacity", "usage")):
                        self._findings = f"Turn failed: {self._turn_error}"
                        self._complete_current_intent(self._findings, "failed")
                        return self._result(QUOTA_ERROR)
                    self._findings = f"Turn failed: {self._turn_error}"
                    self._complete_current_intent(self._findings, "failed")
                    return self._result(ERROR)

                if self._structured_output and self._structured_output.get("type") == "flag_found":
                    candidate = str(self._structured_output.get("flag") or "").strip()
                    if candidate:
                        self._flag = candidate
                        self._findings = f"Flag found via {self._structured_output.get('method', '?')}: {candidate}"
                        if self.no_submit:
                            self._confirmed = True
                    else:
                        self._findings = "Invalid flag_found output: flag is empty; continuing investigation."

                if self._confirmed and self._flag:
                    self._complete_current_intent("flag verified", "completed")
                    return self._result(FLAG_FOUND)
                self._complete_current_intent(self._findings or "intent completed", "completed")
                return self._result(GAVE_UP)

            except asyncio.CancelledError:
                self._complete_current_intent("worker cancelled", "blocked")
                return self._result(CANCELLED)
            except Exception as e:
                error_str = str(e)
                logger.error(f"[{self.agent_name}] Error: {e}", exc_info=True)
                self.tracer.event("error", error=error_str)
                if self._is_transient_turn_error(error_str) and attempt < max_attempts:
                    delay = min(2 ** (attempt - 1), 8)
                    logger.warning(
                        "[%s] Transient solver error on attempt %d/%d: %s; retrying in %ds",
                        self.agent_name,
                        attempt,
                        max_attempts,
                        error_str,
                        delay,
                    )
                    self.tracer.event(
                        "turn_retry",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        error=error_str,
                    )
                    await asyncio.sleep(delay)
                    continue
                self._findings = f"Error: {e}"
                if "quota" in error_str.lower() or "rate" in error_str.lower():
                    self._complete_current_intent(self._findings, "failed")
                    return self._result(QUOTA_ERROR)
                self._complete_current_intent(self._findings, "failed")
                return self._result(ERROR)

    def bump(self, insights: str) -> None:
        self._bump_insights = insights
        self.loop_detector.reset()
        self.tracer.event("bump", insights=insights[:500])

    def _result(self, status: str) -> SolverResult:
        self.tracer.event("finish", status=status, flag=self._flag, confirmed=self._confirmed)
        return SolverResult(
            flag=self._flag, status=status,
            findings_summary=self._findings[:2000],
            step_count=self._step_count,
            cost_usd=self._cost_usd, log_path=self.tracer.path,
            knowledge_queries=self._knowledge_queries,
            knowledge_hits=self._knowledge_hits,
            knowledge_chars=self._knowledge_chars,
        )

    async def stop(self) -> None:
        if self._intent_heartbeat_task:
            self._intent_heartbeat_task.cancel()
            self._intent_heartbeat_task = None
        self.tracer.event("stop", step_count=self._step_count)
        self.tracer.close()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self.sandbox:
            await self.sandbox.stop()
        if self.knowledge_service:
            self.knowledge_service.close()
            self.knowledge_service = None
