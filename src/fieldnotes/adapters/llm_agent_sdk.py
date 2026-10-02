"""The LLM port over the Claude Agent SDK, which runs on the local Claude Code login.

One `ClaudeSDKClient` per call keeps the conversation, so the docs go in once and each update only
carries the new turns. Every tool is off and no filesystem settings are loaded (no CLAUDE.md,
skills, plugins or MCP servers): the model only reads and answers.
"""

import asyncio
import contextlib
import logging
import os
import tempfile
import time

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

logger = logging.getLogger(__name__)

API_KEY_MESSAGE = (
    "ANTHROPIC_API_KEY is set in the environment. Fieldnotes runs on your Claude subscription "
    "through the Claude Code login, and with that variable set the Agent SDK would bill API "
    "credits instead. Unset it (`unset ANTHROPIC_API_KEY`) and run again."
)


class ApiKeyInEnvironment(RuntimeError):
    pass


def refuse_api_key() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise ApiKeyInEnvironment(API_KEY_MESSAGE)


class ClaudeAgentSDKLLM:
    def __init__(self, model: str = "sonnet"):
        refuse_api_key()
        self.model = model
        self._client: ClaudeSDKClient | None = None
        self._options: ClaudeAgentOptions | None = None
        self._context = ""
        self._lock = asyncio.Lock()
        self._closing: set[asyncio.Task] = set()
        # An empty working directory: nothing from this repo leaks into the session.
        self._cwd = tempfile.mkdtemp(prefix="fieldnotes-")

    async def start(self, system_prompt: str, context: str) -> None:
        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            tools=[],
            allowed_tools=[],
            setting_sources=[],
            skills=[],
            mcp_servers={},
            strict_mcp_config=True,
            thinking={"type": "disabled"},
            cwd=self._cwd,
        )
        self._options, self._context = options, context
        async with self._lock:
            self._drop()  # a restart after a failure replaces the old session
            try:
                await self._connect()
            except BaseException:
                self._drop()
                raise

    async def _connect(self) -> None:
        """A fresh session with the docs loaded."""
        client = ClaudeSDKClient(self._options)
        await client.connect()
        self._client = client
        await self._exchange(self._context)

    async def send(self, message: str) -> str:
        async with self._lock:
            if self._client is None:
                raise RuntimeError("LLM session not started (or dropped after a failure)")
            try:
                return await self._exchange(message)
            except BaseException:
                # Cancelled by a timeout or failed mid-answer: the stream may still hold the rest
                # of this answer, which the next call would read as its own. Start over instead.
                self._drop()
                raise

    def _drop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            task = asyncio.get_running_loop().create_task(client.disconnect())
            self._closing.add(task)  # asyncio keeps only weak references to tasks
            task.add_done_callback(self._closing.discard)
            task.add_done_callback(lambda t: t.cancelled() or t.exception())

    async def _exchange(self, message: str) -> str:
        assert self._client is not None
        t = time.perf_counter()
        await self._client.query(message)
        parts: list[str] = []
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                if msg.error:
                    raise RuntimeError(f"Model error: {msg.error}")
                parts += [b.text for b in msg.content if isinstance(b, TextBlock)]
            elif isinstance(msg, ResultMessage):
                if msg.is_error:
                    raise RuntimeError(f"Model call failed: {msg.errors or msg.result}")
                usage = msg.usage or {}
                logger.info(
                    "LLM %s: %.2fs (api %.2fs), in %s (cache read %s), out %s",
                    self.model,
                    time.perf_counter() - t,
                    msg.duration_api_ms / 1000,
                    usage.get("input_tokens"),
                    usage.get("cache_read_input_tokens"),
                    usage.get("output_tokens"),
                )
        return "".join(parts)

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(client.disconnect(), 2)
