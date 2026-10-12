# resume-tailor

This project is a Chrome extension plus a local server. It tailors a one-page LaTeX resume (and an optional cover letter) to a job listing, using a long master content bank. The full spec and milestones are in **plan.md**. Read it before starting any milestone.

## Project skills (`.claude/skills/`)

Load the matching skill before working in its area:

| Skill | Use for |
|---|---|
| `latex-resume-template` | templates, `render.py` escaping, `compile.py` |
| `fact-guards` | `guards/`, the repair loop, and their tests |
| `claude-headless-backend` | `llm/` and anything that calls the model |
| `pipeline-prompts` | `server/prompts/*.md` |
| `chrome-extension-mv3` | everything in `extension/` |
| `bank-authoring` | `bank/master.yaml`, **only when Juhi explicitly asks** |
| `tailor` | running the finished tool on a listing (M5+) |

## Working rules

- **Work one milestone at a time** (M0–M9 in plan.md). When a milestone is done, stop and summarize what changed, what's tested, and any open questions. Wait for review before starting the next one.
- **Never invent resume content.** Use `bank/fixture.yaml`, which is clearly fake data, for all development and tests. Don't read, edit, or generate content for `bank/master.yaml` unless asked explicitly. That file is Juhi's real data.
- **Ask before changing an invariant** (listed below) or adding a dependency not named in plan.md.
- Prefer small, reviewable diffs. Don't refactor across modules outside the current milestone.

## Invariants (do not break)

1. **The model never writes LaTeX.** LLM stages return JSON with plain-text strings, validated by pydantic. All LaTeX comes from `server/templates/*.j2`. All escaping goes through the single function in `render.py`.
2. **Provenance on every generated bullet or paragraph.** Each one carries `source_ids` that resolve to bank bullet or context IDs. These IDs are stored in `run.json` and never rendered.
3. **Guards run on every rewrite.** The fact diff (deterministic) runs first, then the verifier (a separate LLM call). A bullet that fails gets one repair attempt, then falls back to the original source text. There is no code path that skips the guards.
4. **The fact diff compares against cited sources only**, not the whole bank.
5. **Tests never call the real `claude` CLI.** Use `llm/replay.py` fixtures.
6. **The server binds to 127.0.0.1 only** and requires the `X-Tailor-Token` header. CORS is allowed for the extension origin only.
7. **Tectonic runs without shell-escape.**

## Stack

| Part | Language / tools |
|---|---|
| Server + pipeline (`server/`) | Python 3.12, uv, FastAPI, pydantic v2, Jinja2, pypdf, pdfplumber, pytest |
| Extension (`extension/`) | TypeScript, Chrome MV3, esbuild or Vite, @mozilla/readability |
| Resume templates | LaTeX (Jake's Resume style) through Jinja2 with `\VAR{}` / `\BLOCK{}` delimiters |
| Content bank | YAML (`bank/*.yaml`) |
| TeX engine | Tectonic |
| LLM | headless Claude Code (`claude` CLI, print mode, JSON output, tools disabled) |

## Commands

```bash
make test          # pytest (server) + extension tests
make serve         # run local server on 127.0.0.1:8765
make ext           # build extension to extension/dist (load unpacked in Chrome)
make lint          # ruff check + ruff format --check + mypy --strict
make check         # verify tectonic + claude CLI are installed; warm the TeX cache
uv run python -m tailor check [--warm]        # same check, without make
uv run python -m tailor run path/to/listing.txt --profile fde [--cover-letter]
uv run python -m tailor render --all          # render whole bank (visual check)
uv run python -m tailor bank lint             # bank quality checks (M9)
```

Keep these working. If you add a command, document it here.

## Headless Claude Code backend

- Before editing `llm/claude_cli.py`, run `claude --help` to check the current flag names. Don't assume them.
- Run the CLI from `~/.resume-tailor/llm-cwd/` (an empty directory), so this repo's CLAUDE.md and settings don't leak into pipeline prompts.
- Disable all tools. Use JSON output. Set a timeout per call (120s by default) and a concurrency limit of 3. Validate output with pydantic, retry once with the validation error attached, then raise a typed error.

## Conventions

- **Python:** type hints everywhere. Use pydantic models at every stage boundary and a `ruff` + `mypy --strict` clean `server/tailor/`. Write async for I/O (subprocess, server) and plain functions for pure logic.
- **Prompts** live in `server/prompts/<stage>.md`, each with a `version:` header. Record the version in `run.json`. Don't inline prompts in Python.
- **Cover-letter voice** lives in `server/prompts/_juhi_voice.md`. Private writing samples live in `bank/voice_examples.md` (gitignored; read it only for M8 prompt work). Never copy facts from the samples into prompts or fixtures.
- **IDs:** use kebab-case with a type prefix: `exp-`, `proj-`, `lead-`, `edu-`, `award-`. Bullets end in `-bN` and context items in `-cN`.
- **TypeScript:** strict mode. Each site extractor gets its own file in `extension/src/extractors/` with an HTML fixture test.
- **Errors:** pipeline stages raise typed errors (`ListingParseError`, `GuardFailure`, `CompileError`, `LLMError`). The server maps them to SSE `error` events with a human-readable message.
- **Outputs** go to `applications/` (gitignored). Never write outside the repo or `~/.resume-tailor/`.

## Testing priorities

1. `guards/factdiff.py`: the heaviest coverage, including adversarial cases (a number moved between bullets, a team claim turned into an individual one, tech aliases, normalized numbers).
2. The LaTeX escaping round-trip.
3. Fit-loop invariants: the result is one page, `min_keep` bullets are kept, and every entry keeps at least 2 bullets.
4. End-to-end runs on the fixture bank with replay, asserting selected IDs and guard results, not exact wording.

## Gitignore

`applications/`, `bank/master.yaml`, `~/.resume-tailor/`, `extension/dist/`, `.venv/`, `*.pdf` outside `tests/fixtures/`.
