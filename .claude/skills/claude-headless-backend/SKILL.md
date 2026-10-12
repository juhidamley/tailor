---
name: claude-headless-backend
description: Use when writing or debugging server/tailor/llm/ (claude_cli.py, replay.py, base.py), or any pipeline stage that calls the model. Covers running the `claude` CLI headlessly as a pure JSON function, isolation, parsing, retries, concurrency, and record/replay fixtures.
---

# Headless Claude Code as the LLM backend

The pipeline treats the model as a pure function: **prompt in, validated pydantic object out.** No tools, no files, no memory between calls.

## Step 0: check the real CLI

Before writing or changing `claude_cli.py`, run:

```bash
claude --version
claude --help
```

Map each behavior below to the flags that actually exist. Write the mapping into a comment at the top of `claude_cli.py`, along with the CLI version you checked. Flags I expect, which you must **confirm**, not assume:

| Behavior | Likely flag |
|---|---|
| Non-interactive, print and exit | `-p` / `--print` |
| Machine-readable result envelope | `--output-format json` |
| Model choice | `--model <name>` |
| No tools at all | `--tools ""` or `--disallowedTools …` or `--allowedTools ""` (check which one fully disables tools) |
| Replace the default system prompt | `--system-prompt` |
| Don't save the session | `--no-session-persistence` (if present) |
| Limit agent turns | `--max-turns 1` |
| Schema-constrained output | `--json-schema` (if present; otherwise use prompt plus validation) |

If a flag doesn't exist, use the fallback in the right column of your mapping comment, and note it in the milestone summary.

## Isolation

- Run with `cwd=~/.resume-tailor/llm-cwd/`. Create it if it's missing and keep it empty. That way no repo `CLAUDE.md`, `.claude/` settings, or skills affect pipeline prompts.
- Pass the prompt through **stdin**, not argv. Prompts carry the whole bank listing and can go past argv limits, and argv shows up in `ps`.
- Use a minimal environment: inherit `PATH`, `HOME`, and auth-related variables, and drop anything project-specific.
- Use `asyncio.create_subprocess_exec` (never `shell=True`).

## The call

```python
async def complete_json(self, prompt: str, schema: type[T], *, stage: str) -> T:
    async with self._sem:                      # concurrency limit (config, default 3)
        raw = await self._run(prompt, timeout=cfg.llm_timeout_s)   # 120s default
    try:
        return schema.model_validate(extract_json(raw))
    except (ValidationError, JSONDecodeError) as e:
        retry_prompt = prompt + RETRY_SUFFIX.format(error=short(e), schema=schema.model_json_schema())
        async with self._sem:
            raw = await self._run(retry_prompt, timeout=cfg.llm_timeout_s)
        try:
            return schema.model_validate(extract_json(raw))
        except (ValidationError, JSONDecodeError) as e2:
            raise LLMError(stage=stage, detail=short(e2), raw_excerpt=raw[:500]) from e2
```

## Parsing the output

With `--output-format json`, stdout is an **envelope**, and the model's text sits in a field (probably `result`). Check against a real run, and save one real envelope as `tests/fixtures/llm/envelope_sample.json`.

`extract_json(envelope)` should:
1. Parse the envelope. If it has an error flag or subtype, raise `LLMError` with that message (this covers auth expired, rate limit, and overload).
2. Take the text field.
3. Strip a fenced code block if one is present (```json … ```).
4. Otherwise, take the substring from the first `{` or `[` to its matching closing bracket, using a bracket counter that understands strings.
5. Call `json.loads`.

Every stage prompt ends with: *"Respond with only a JSON object matching this schema. No prose, no code fences."* Then include `schema.model_json_schema()`.

## Failure modes to handle

| Symptom | Handling |
|---|---|
| `claude` not on PATH | `/health` reports it, and the CLI prints the install hint |
| Not logged in or auth expired | Envelope error, so `LLMError("Claude Code isn't signed in — run `claude` once in a terminal")` |
| Timeout | Kill the process group and raise `LLMError(stage, "timeout")`. No silent retry, since retries happen at the stage level |
| Usage limit reached | Surface the CLI's message verbatim to the extension |
| Non-JSON chatter | Handled by `extract_json`, then the schema retry |

## Cost and latency

Each `claude -p` process takes a few seconds to start. Keep calls coarse:
- one JobSpec call
- one ranking call
- one rewrite call **per entry**, run in parallel
- one verifier call **per entry**, with all bullets batched
- repairs only for the bullets that failed

Log `stage`, duration, prompt size, and token usage (if the envelope reports it) for every call into `run.json` under `llm_calls`.

## Record and replay (llm/replay.py)

- `ReplayLLM(mode="replay"|"record", dir=tests/fixtures/llm/)`
- The key is `sha256(stage + "\n" + normalized_prompt)[:16]`. Normalization collapses whitespace and strips the prompt `version:` line, so a version bump alone doesn't invalidate fixtures. Changing the prompt *body* does invalidate them, and that's intended.
- `record` wraps the real backend and writes `{key}.json` (prompt excerpt, stage, response text).
- `replay` raises `MissingFixture(key, stage, prompt_head)` on a miss. **Never fall back to the real CLI.**
- `make record-fixtures` is the only target that runs `record`. It's opt-in, and you must report which fixtures changed.
- pytest has a session-wide guard that fails if `claude_cli` is constructed during tests.
