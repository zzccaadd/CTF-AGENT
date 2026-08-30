#!/usr/bin/env python3
"""Minimal end-to-end probe: can a real Codex thread see and call search_knowledge?

Spawns `codex app-server` and drives the same JSON-RPC flow as CodexSolver
(initialize -> thread/start -> turn/start -> tool call -> turn/completed), but
instructs the model to call search_knowledge immediately and report the result.

Purpose: prove the tool is callable over the real protocol with the real local
knowledge DB (costs a fraction of a cent), separate from whether the model
chooses to call it during benchmark runs.

Exit codes:
  0  model called search_knowledge and the loop completed
  1  no search_knowledge call was observed
  2  protocol failure (start/thread error)
"""

from __future__ import annotations

import asyncio
import itertools
import json
import sys

from backend.agents.codex_solver import SANDBOX_TOOLS
from backend.knowledge.service import KnowledgeService
from backend.output_types import solver_output_json_schema

MODEL = "gpt-5.5"
INSTRUCTION = (
    "Protocol verification session. Your ONLY task: call the search_knowledge tool "
    "exactly once with query 'ELF e_entry', then report the returned source_url and title. "
    "Do not call any other tool and do not perform any analysis."
)


async def run() -> int:
    tool = next(tool for tool in SANDBOX_TOOLS if tool["name"] == "search_knowledge")
    proc = await asyncio.create_subprocess_exec(
        "codex", "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    ids = itertools.count(1)
    pending: dict[int, asyncio.Future] = {}
    service = KnowledgeService.from_path("logs/knowledge.sqlite3")
    called = False
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

    async def respond(request_id: int, result: dict) -> None:
        proc.stdin.write((json.dumps({"id": request_id, "result": result}) + "\n").encode())
        await proc.stdin.drain()

    async def read_loop() -> None:
        nonlocal called
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
                        future.set_exception(RuntimeError(f"RPC error: {msg['error']}"))
                    else:
                        future.set_result(msg)
                continue
            method = msg.get("method", "")
            params = msg.get("params", {})
            if method == "item/tool/call" and msg_id is not None:
                tool_name = params.get("tool", "")
                args = params.get("arguments", {})
                print(f"[probe] tool call received: {tool_name} {json.dumps(args, ensure_ascii=False)}", flush=True)
                if tool_name == "search_knowledge":
                    called = True
                    results = service.search(str(args.get("query", "")))
                    payload = {
                        "results": [result.__dict__ for result in results],
                        "diagnostic": service.last_diagnostic,
                    }
                    text = json.dumps(payload, ensure_ascii=False)
                else:
                    text = f"unexpected tool: {tool_name}"
                await respond(msg_id, {"contentItems": [{"type": "inputText", "text": text}], "success": True})
            elif method == "item/completed":
                item = params.get("item", params)
                if item.get("type") == "agentMessage" and item.get("text"):
                    print(f"[probe] assistant: {item['text'][:400]}", flush=True)
            elif method == "turn/completed":
                print(f"[probe] turn/completed status={params.get('turn', {}).get('status')}", flush=True)
                turn_done.set()

    reader = asyncio.create_task(read_loop())
    try:
        await rpc("initialize", {
            "clientInfo": {"name": "ctf-agent-probe", "version": "0.1"},
            "capabilities": {"experimentalApi": True},
        })
        await notify("initialized", {})
        resp = await rpc("thread/start", {
            "model": MODEL,
            "personality": "pragmatic",
            "baseInstructions": INSTRUCTION,
            "cwd": "/tmp",
            "approvalPolicy": "on-request",
            "sandbox": "read-only",
            "serviceTier": "flex",
            "dynamicTools": [tool],
        })
        thread_id = resp["result"]["thread"]["id"]
        print(f"[probe] thread started: {thread_id}", flush=True)
        await rpc("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": "Begin now."}],
            "outputSchema": solver_output_json_schema(),
        })
        try:
            await asyncio.wait_for(turn_done.wait(), 240)
        except TimeoutError:
            print("[probe] timeout waiting for turn completion", file=sys.stderr)
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except TimeoutError:
            proc.kill()
        service.close()
        reader.cancel()

    if not called:
        print("[probe] search_knowledge was NOT called by the model", file=sys.stderr)
        return 1
    print("[probe] search_knowledge callable end-to-end: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
