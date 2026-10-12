# resume-tailor — Development Plan

You are building **resume-tailor**: a Chrome extension plus a local server. It takes a job listing and produces a tailored, one-page LaTeX resume and an optional cover letter. All content comes from a long master content bank, and guards ensure no claim goes beyond the bank.

Work **one milestone at a time**. At the end of each milestone, stop, summarize what changed, and wait for review before moving on. **Never invent resume content.** The bank is written and fact-checked by the owner (Juhi). Use only the placeholder fixture bank (`bank/fixture.yaml`) until the real one exists.

---

## 1. Architecture

```
┌────────────────────┐        HTTP + SSE         ┌──────────────────────────────────────┐
│ Chrome extension   │  ───────────────────────► │ Local server (FastAPI, 127.0.0.1)    │
│ (MV3, side panel)  │  ◄─────────────────────── │                                      │
│ - extract listing  │   progress, report, PDFs  │  pipeline:                           │
│ - pick profile     │                           │  parse → select → rewrite →          │
│ - show report      │                           │  guards → render → compile → fit     │
└────────────────────┘                           │                                      │
                                                 │  LLM: headless Claude Code (claude -p)│
                                                 │  TeX: Tectonic                       │
                                                 │  Bank: bank/master.yaml + profiles   │
                                                 │  Output: applications/<run>/         │
                                                 └──────────────────────────────────────┘
```

**Core invariants:**
1. **The model never writes LaTeX.** It returns structured JSON with plain-text bullets. Code escapes the text and renders it through a Jinja2 template.
2. **Every output bullet carries `source_ids`**, the bank bullet or context IDs it was built from. These IDs are stored in `run.json` and never printed on the resume.
3. **Guards run on every rewrite.** A deterministic fact diff runs first, then a verifier model pass. A bullet that fails is retried once with feedback. If it fails again, it **falls back to the original source text**.
4. **Everything about a run is saved.** You can always trace what was sent to which company.

## 2. Repo layout

```
resume-tailor/
  server/
    tailor/
      __init__.py
      config.py          # paths, port, token, model flags, page limits
      bank.py            # load + validate bank (pydantic models)
      listing.py         # clean listing text → JobSpec (LLM)
      select.py          # score + select entries/bullets
      rewrite.py         # rewrite selected bullets with provenance (LLM)
      guards/
        factdiff.py      # deterministic extraction + comparison
        verifier.py      # LLM overclaim check
      render.py          # Jinja2 (LaTeX-safe delimiters) + escaping
      compile.py         # Tectonic wrapper, page count, fill measurement
      fit.py             # auto-fit-to-one-page loop
      cover_letter.py
      report.py          # fit report (covered/missing keywords, reverts, flags)
      llm/
        base.py          # LLM interface: complete_json(prompt, schema) -> dict
        claude_cli.py    # headless Claude Code implementation
        replay.py        # record/replay backend for tests
      runs.py            # applications/<run>/ persistence
      api.py             # FastAPI app
      cli.py             # `python -m tailor run listing.txt --profile fde`
    templates/
      resume.tex.j2      # Jake's Resume style
      cover_letter.tex.j2
    prompts/             # one .md prompt per LLM stage, versioned
    tests/
  extension/
    manifest.json        # MV3
    src/
      background.ts
      content.ts         # listing extraction
      extractors/        # linkedin.ts, greenhouse.ts, lever.ts, ashby.ts, workday.ts, generic.ts
      sidepanel/         # UI
    build config (Vite or esbuild)
  bank/
    master.yaml          # real bank (Juhi), gitignored or private repo
    fixture.yaml         # fake bank for development/tests
    profiles.yaml
  applications/          # run outputs, gitignored
  CLAUDE.md
```

Use Python 3.12 with `uv`, FastAPI, pydantic v2, Jinja2, pypdf/pdfplumber, and pytest. Write the extension in TypeScript, with Mozilla Readability as the generic extractor.

## 3. Bank schema (`bank/master.yaml`)

The bank is meant to be **long and thorough**. It holds far more than fits on one page.

```yaml
contact: { name, email, phone, website, github, linkedin, location }

education:
  - id: edu-cmc
    school: Claremont McKenna College
    degree: "B.A. Computer Science"
    dates: { start: 2024-08, end: 2028-05 }
    details: [ ... ]          # coursework, GPA, honors; each item has id + tags

experiences:                  # jobs, research, RA work
  - id: exp-<slug>
    org: ...
    role: ...
    location: ...
    dates: { start: YYYY-MM, end: YYYY-MM | present }
    tags: [ml, finance, research, ...]
    context:                  # NOT printed. Facts a rewrite may draw on.
      - id: exp-<slug>-c1
        text: "Team of 3; I owned the data pipeline; ~2M rows/day"
    bullets:
      - id: exp-<slug>-b1
        text: "Original, owner-approved bullet text"
        tags: [python, pipelines, ml]
        skills: [Python, PyTorch, SLURM]
        strength: 4           # 1–5, owner's judgment of impressiveness
        min_keep: false       # true = never dropped by the fit loop

projects:      # same shape as experiences, with an optional link field
leadership:    # same shape (e.g., Girls Who Code)
skills:
  - category: Languages
    items:
      - { name: Python, evidence: [exp-x-b1, proj-y-b2] }   # every skill needs evidence
awards: [ { id, text, date, tags } ]
```

**Validation rules in `bank.py`:** all IDs are unique, and every skill has at least one evidence ID that resolves. Dates must parse. Bullets are plain text: `% $ & # _` are allowed as written (`40%`, `$2M`, `R&D`, `C#`), because `render.py` escapes them. What validation rejects is LaTeX markup: backslash commands, braces, and math mode. Every bullet and context item has `status: proposed | approved`, and only `approved` items reach the pipeline.

`bank/profiles.yaml` defines **four profiles**: `swe_ml`, `fde`, `pm`, `research_quant`. Each one sets:
- `tag_weights` (for example, `pm: {leadership: 2.0, users: 1.8, ml: 0.8}`)
- `section_order` (for example, PM puts Leadership above Projects)
- `skills_categories` to show
- `max_bullets_per_entry`

If the user doesn't pick a profile, the server picks the closest one from the JobSpec and reports which it chose.

## 4. Pipeline

### 4.1 Listing → JobSpec
The input is the listing text (from the extension or a pasted .txt), with an optional URL.

The LLM returns:
```json
{ "company": "", "title": "", "seniority": "", "location": "",
  "must_haves": [], "nice_to_haves": [], "keywords": [],
  "responsibilities": [], "company_signals": [], "suggested_profile": "" }
```
`company_signals` holds mission or product statements quoted from the listing. They are the only company facts the cover letter may use.

### 4.2 Select
1. Run a deterministic pre-score per bullet: `strength × profile tag weight × keyword overlap (stemmed, case-insensitive) with the JobSpec`.
2. Run an LLM ranking pass. Input: the JobSpec and a compact bank listing (`id | entry | text | tags`). Output: entries to include, and an ordered list of bullet IDs per entry with a relevance score from 0 to 1.
3. Combine: final score = 0.6 × LLM + 0.4 × normalized pre-score. Save both scores in `run.json`.
4. Select generously, about 1.5× what fits. The fit loop trims later.

### 4.3 Rewrite
For each selected entry, the LLM gets the JobSpec, the entry's selected bullets, and its `context` items, each with IDs. It returns:
```json
{ "bullets": [ { "text": "...", "source_ids": ["exp-x-b1", "exp-x-c2"] } ] }
```

The rewrite prompt sets these rules:
- Use the listing's vocabulary only where the source supports it.
- Every claim must trace to a cited source.
- Don't add numbers, tools, scope, or outcomes the sources don't contain.
- Use past tense for past roles and present tense for current ones.
- Start each bullet with a strong verb, with no first person.
- Aim for at most about 2 rendered lines (a configurable character budget, default 210).
- Use plain text only.
- Merging two source bullets into one is allowed if both IDs are cited.

### 4.4 Guard A — fact diff (`guards/factdiff.py`, deterministic)
For each rewritten bullet, extract the following from both the rewrite and the **union of its cited sources only**:
- **Numbers:** integers, decimals, %, $, multipliers like "3x", ranges, "~", "k/M/B" suffixes. Normalize before comparing, so "40 percent" equals "40%" and "2M" equals "2,000,000".
- **Tech and skill terms:** match against a lexicon built from every bank `skills` entry plus `server/tailor/guards/tech_lexicon.txt`. The lexicon must handle multi-word terms, case, and aliases ("PyTorch" equals "pytorch"; "k8s" equals "Kubernetes").
- **Proper nouns:** capitalized tokens not at the start of a sentence, and not in a stopword or verb list.
- **Scope words:** led, managed, owned, founded, architected, sole, "team of N". These are flagged if the rewrite has one and the sources don't.

Results:
- `hard_fail`: a new number, or a new tech term.
- `soft_flag`: a new proper noun or scope word. It is sent to the verifier with this note attached.

Write thorough unit tests here. This is the most important deterministic code in the project.

### 4.5 Guard B — verifier (`guards/verifier.py`, LLM)
The verifier runs in a separate `claude -p` call that has **not** seen the rewrite prompt. It gets the source texts, the rewrite, and any soft flags. It returns, per bullet:
```json
{ "verdict": "supported | overclaim | unsupported", "issues": ["..."], "suggested_fix": "..." }
```
Its rubric checks for:
- inflated role ("helped" → "led")
- invented outcomes or impact
- individual credit for team work
- added certainty
- changed timeframe
- implied tools or methods not in the sources

### 4.6 Repair
A bullet with a `hard_fail` or a non-`supported` verdict goes back to rewrite **once**, with the guard feedback attached. It then runs through both guards again. If it still fails, the tool uses the highest-scored cited source bullet's original text and records the revert in the report.

### 4.7 Render
- Use Jinja2 with LaTeX-safe delimiters: `\VAR{}`, `\BLOCK{}`, and `\#{}` for comments.
- Escape every string in one tested function (`& % $ # _ { } ~ ^ \`, plus smart quotes and dashes).
- The template is in **Jake's Resume** style:
  - single column
  - `\resumeSubheading` / `\resumeItem` macro style
  - `\pdfgentounicode=1` for ATS text extraction
  - no tables-in-tables
  - no icons in the text layer

### 4.8 Compile + auto-fit (`compile.py`, `fit.py`)
- Compile with **Tectonic**, with no shell-escape. Count pages with pypdf, and measure vertical fill with pdfplumber (the y-position of the last text line).
- Fit loop, with at most 12 iterations:
  1. If the resume runs over one page, drop the globally lowest-scored bullet that is not `min_keep`. Keep at least 2 bullets per included entry. Below that, drop the lowest-scored whole entry instead.
  2. If the page is less than 88% full and there are unused selected bullets, add back the highest-scored one. Stop if that causes overflow, and revert it.
  3. Margin and spacing tweaks are allowed only within config bounds (for example, a font of 10–11pt and margins of 0.5–0.75in). Prefer dropping content to shrinking the type.
- Log each iteration to `run.json`.

### 4.9 Cover letter (in Juhi's voice)
- One page, 250–350 words, rendered from `cover_letter.tex.j2` with a header that matches the resume.
- **Voice:** the `cover_letter` prompt includes `server/prompts/_juhi_voice.md` (style rules, committed) and then `bank/voice_examples.md` (excerpts of her own writing, gitignored, loaded only if present). The voice file controls *how* things are said; `_truth_rules.md` still controls *what* is claimed. The examples are tone references, **never sources**.
- **Structure** follows her March 2026 letter: salutation, a one-line opener with a direct ask, a connection paragraph, a bridge sentence, three `**Label**: proof` bullets mapped to `must_haves`, an optional fit/gap line, and the close.
- **Inputs:** the JobSpec and `company_signals`, the top-scored selected bullets and context, approved bank `stories` (items with `use: [cover_letter]`), and an optional **`personal_note`**: Juhi's own one or two sentences on why this company. The connection paragraph may draw only on `personal_note`, approved `stories`, or `company_signals`. It must never invent a personal experience. When `personal_note` is empty, it writes a specific observation about the company instead.
- **Output:** `{paragraphs: [{text, source_ids}], bullets: [{label, text, source_ids}], contact_name?}`. `personal_note` gets the pseudo-ID `note-personal`, and listing signals get `sig-N`, so the fact guards can check against them.
- **Guards:** the same fact diff and verifier run per paragraph and per bullet (cited sources only). Then a deterministic **voice lint** runs (`guards/voice_lint.py`) with these rules:
  - no `—` (convert to an unspaced `–`)
  - no ` - ` used as a dash
  - no exclamation marks
  - no banned phrases (list in `_juhi_voice.md`, mirrored in code)
  - 250–350 words
  - exactly 3 bullets

  A lint failure triggers one repair call. If it fails again, the lint result is reported but the letter is not blocked.
- The cover letter is optional (`cover_letter: true` in the request).

### 4.10 Persist (`runs.py`)
Each run is saved to `applications/YYYY-MM-DD_<company-slug>_<role-slug>/`, which holds:
- `listing.txt` and `listing_url.txt`
- `jobspec.json`
- `run.json`, with selections, scores, provenance, guard results, fit iterations, prompt versions, and the bank file hash
- `resume.tex` and `resume.pdf`
- `cover_letter.tex` and `cover_letter.pdf`
- `report.md`

`report.md` lists:
- the profile used
- must-haves and keywords covered or missing, with missing ones split into "not in bank" and "in bank but dropped for space"
- reverted bullets and verifier flags
- the final page fill

## 5. LLM backend: headless Claude Code (`llm/claude_cli.py`)

- Implement the `LLM` interface (`complete_json(prompt: str, schema: type[BaseModel]) -> BaseModel`) by running the `claude` CLI in non-interactive print mode with JSON output, as an async subprocess.
- **Check the current CLI flags with `claude --help` before writing this. Do not assume flag names.** The behaviors needed are:
  - print / non-interactive mode
  - JSON output format
  - model selection from config
  - **all tools disabled** (it's a pure text task)
  - no session persistence, if supported
- Run it from a dedicated empty working directory (for example, `~/.resume-tailor/llm-cwd/`), so no project `CLAUDE.md` or settings leak into the prompts.
- Parse the response. Pull the JSON out of the result field, tolerating a fenced code block, and validate it with pydantic. On a validation error, retry once with the error message attached. After that, raise a typed error.
- Set a timeout per call (default 120s) and a concurrency limit (default 3). Rewrite calls for different entries may run in parallel.
- `llm/replay.py` records prompt-hash → response to `tests/fixtures/llm/` and replays it in tests. **Tests must never call the real CLI.**
- Keep the interface small, so an Anthropic SDK backend can be added later without touching the pipeline.

## 6. Local server (`api.py`)

Bind to `127.0.0.1:8765` only. Require an `X-Tailor-Token` header, with the token generated on first run and stored in `~/.resume-tailor/config.toml`. Allow CORS only from the extension's `chrome-extension://<id>` origin.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Returns the version, whether Tectonic is found, whether the `claude` CLI is found, and whether the bank is valid |
| GET | `/profiles` | Lists the profiles |
| POST | `/runs` | Body: `{listing_text, url?, profile?, cover_letter: bool, personal_note?, contact_name?}`. Returns `{run_id}` |
| GET | `/runs/{id}/events` | SSE stream of stage progress: parsing, selecting, rewriting n/m, guarding, fitting i, done or error |
| GET | `/runs/{id}` | Returns the summary and `report.md` content |
| GET | `/runs/{id}/files/{name}` | Returns the PDF, .tex, or report |
| GET | `/runs` | Lists recent runs |

Runs execute as background asyncio tasks, one at a time (queue the rest). Also add a CLI (`python -m tailor run <listing.txt|-> --profile fde [--cover-letter]`) that uses the same pipeline. **Build and test the CLI before the server.**

Add a `launchd` plist template and a `make install-agent` target, so the server starts at login on macOS.

## 7. Chrome extension (MV3)

**Side panel UI:**
- the current tab's detected listing, as an editable textarea
- a profile dropdown with "Auto" as the default
- a cover-letter checkbox; when checked, it shows a "Why this company? (your words, optional)" textarea (`personal_note`) and a contact-name field
- a Tailor button
- live stage progress from SSE, read with `fetch` plus a stream parser, because `EventSource` can't send the token header
- the result: open or download the PDF and .tex, and the rendered `report.md`
- a recent runs list
- a status dot showing server health, plus a "server not running" help state

**Listing extraction (`content.ts`):**
1. If the user has text selected, use that.
2. Otherwise, use a site-specific extractor: LinkedIn job view, Greenhouse, Lever, Ashby, Workday. Each one targets the job description container and title/company fields. Keep each in its own file with a small fixture test, using saved HTML.
3. Otherwise, use Readability on the whole page.

Always show the extracted text so the user can fix it before submitting. A "Paste listing" mode works on any page.

**Permissions:**
- `sidePanel`, `activeTab`, `scripting`, `storage`
- host permission only for `http://127.0.0.1:8765/*`
- the content script is injected on demand via `activeTab`, with no broad host permissions

Store the token in `chrome.storage.local`, set via an options page.

## 8. Testing

- **Unit:** escaping, bank validation, fact-diff extraction and normalization (heavy: 40+ cases, including adversarial ones such as a number moved between bullets, a "team" claim turned into "I", or a tech alias), and slugging.
- **Fit loop:** use synthetic banks with known line counts. Assert that it ends on one page, keeps `min_keep` bullets, and keeps at least 2 bullets per entry.
- **Pipeline:** run end to end on `bank/fixture.yaml` with the replay LLM, using 3 sample listings (an ML engineer role, an FDE role, a PM role). Make golden assertions on the selected IDs and on all guards passing, not on exact text.
- **Guard red-team test:** feed hand-written bad rewrites through the guards and assert they are caught.
- **Extension:** extractor tests against saved HTML fixtures.

## 9. Milestones (stop for review after each)

- **M0 — Skeleton.** Set up the repo, the uv project, `CLAUDE.md` (copy the invariants from section 1), the Makefile (`make test`, `make serve`, `make ext`), and a check that Tectonic is installed.
- **M1 — Bank + render.** Build the pydantic schema and validator, `fixture.yaml`, `profiles.yaml`, the Jake's-style template, and escaping. `python -m tailor render --all` should render the *entire* fixture bank to a multi-page PDF, as a visual check.
- **M2 — LLM backend.** Build `claude_cli.py`, the replay backend, and `complete_json` with schema validation and retry. Smoke test: `python -m tailor llm-ping`.
- **M3 — Pipeline, no guards.** Build listing → JobSpec → select → rewrite → render → compile, through the CLI.
- **M4 — Guards + repair.** Build the fact diff (with its full test suite), the verifier, the repair loop, and source-text fallback.
- **M5 — Auto-fit + persistence + report.**
- **M6 — Server.** Build the FastAPI endpoints, SSE, token auth, and the launchd agent.
- **M7 — Extension.** Build the side panel, extractors, server connection, and results view.
- **M8 — Cover letter.** Build `_truth_rules.md`, the `cover_letter` prompt including `_juhi_voice.md` and `bank/voice_examples.md`, `voice_lint.py` with tests, `personal_note` support in the CLI, API, and extension, and approved `stories` as sources. Test on the 3 sample listings, with and without a `personal_note`.
- **M9 — Polish.** Version prompts in `prompts/` (record the version in `run.json`), add a `tailor bank lint` command (finds bullets with no tags, skills with weak evidence, near-duplicate bullets), and write the README.

## 10. Out of scope (for now)

- auto-submitting applications or filling forms
- a cloud backend
- multiple users
- an Anthropic SDK backend (keep the interface ready for it)
