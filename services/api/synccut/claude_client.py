"""One place that talks to Claude, whatever credential is configured.

- Console API key (``sk-ant-api…``): the Anthropic API SDK (Messages API) with
  JSON-schema structured output and server-side refusal fallback.
- OAuth token (``sk-ant-oat…``, from a Claude login / ``claude setup-token``):
  the Claude Agent SDK, which runs Claude Code and accepts that token as
  ``CLAUDE_CODE_OAUTH_TOKEN``. Tools are off and it answers in one turn.

Callers only see ``ask_json(prompt, schema)`` → dict.
"""

from __future__ import annotations

import asyncio
import json
import logging

from .config import settings

log = logging.getLogger("synccut.claude")


def credential_kind() -> str | None:
    if settings.anthropic_auth_token:
        return "oauth"
    if settings.anthropic_api_key:
        return "oauth" if settings.anthropic_api_key.startswith("sk-ant-oat") else "api_key"
    return None


def ask_json(prompt: str, schema: dict, *, effort: str = "low", timeout: float = 180) -> dict:
    kind = credential_kind()
    if kind is None:
        raise RuntimeError("no Anthropic credential configured")
    if kind == "oauth":
        return _agent_sdk_json(prompt, schema, effort=effort, timeout=timeout)
    return _messages_json(prompt, schema, effort=effort, timeout=timeout)


# ── Claude Agent SDK (OAuth token) ─────────────────────────────────────────


def _agent_sdk_json(prompt: str, schema: dict, *, effort: str, timeout: float) -> dict:
    import claude_agent_sdk as sdk

    token = settings.anthropic_auth_token or settings.anthropic_api_key
    options = sdk.ClaudeAgentOptions(
        model=settings.claude_model,
        tools=[],                 # a pure text task: no file, shell or web tools
        max_turns=2,
        setting_sources=[],       # don't load user/project settings or CLAUDE.md
        cwd=str(settings.data_dir),
        effort=effort,
        output_format={"type": "json_schema", "schema": schema},
        env={"CLAUDE_CODE_OAUTH_TOKEN": token, "ANTHROPIC_API_KEY": ""},
    )

    async def run() -> dict:
        result = None
        async for message in sdk.query(prompt=prompt, options=options):
            if isinstance(message, sdk.ResultMessage):
                result = message
        if result is None:
            raise RuntimeError("Claude returned no result")
        if result.is_error:
            raise RuntimeError(f"Claude failed ({result.subtype}, status {result.api_error_status}): {result.errors or result.result}")
        data = result.structured_output if result.structured_output is not None else json.loads(result.result or "")
        log.info("Claude (Agent SDK) answered in %s ms, cost $%.4f", result.duration_ms, result.total_cost_usd or 0)
        return data

    try:
        return _run_coroutine(lambda: asyncio.wait_for(run(), timeout))
    except sdk.CLINotFoundError as exc:
        raise RuntimeError("the Claude Code runtime bundled with claude-agent-sdk was not found") from exc
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"Claude took longer than {timeout:.0f}s") from exc


def _run_coroutine(make):
    """Run a coroutine to completion from sync code, even when called inside a running
    event loop (e.g. from an ``async def`` FastAPI endpoint): then it runs on a worker thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make())
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(make())).result()


# ── Anthropic API SDK (API key) ───────────────────────────────────────────


def _messages_json(prompt: str, schema: dict, *, effort: str, timeout: float) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3, timeout=timeout)
    request = dict(
        model=settings.claude_model,
        max_tokens=16000,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        # Server-side fallback: if the model declines, the API reroutes within the same call.
        response = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request)
    except anthropic.BadRequestError as exc:
        log.info("fallback parameter rejected (%s); retrying without it", exc.message)
        response = client.messages.create(**request)
    except anthropic.AuthenticationError as exc:
        raise RuntimeError("Anthropic API key was rejected") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Anthropic rate limit hit after retries") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("could not reach the Anthropic API") from exc

    if response.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("response was cut off")
    return json.loads(next(b.text for b in response.content if b.type == "text"))
