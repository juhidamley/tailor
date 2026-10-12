---
name: bank-authoring
description: Use only when Juhi explicitly asks to add, edit, or expand her content bank (bank/master.yaml), mine a codebase for resume material, or interview her about an experience. Covers the bank schema, writing strong source bullets, context items, tagging and strength, mining a repo for facts, and interview questions.
---

# Authoring the content bank

`bank/master.yaml` is Juhi's real record. The guards treat it as ground truth, so **anything wrong in the bank becomes something wrong on every resume.** Accuracy comes before polish.

## Hard rules

1. **Only she can make a claim.** You may *propose* bullets and context items, but every one starts as `status: proposed`. Set it to `approved` only after she confirms it in this session. The pipeline ignores `proposed` items. Add `status` to the schema if it isn't there yet, and ask before changing the schema.
2. **Never guess a metric.** If a repo or conversation suggests a number but doesn't state it, write the question down, not the number.
3. **Keep diffs small and show them.** After an edit, show the added or changed YAML and run `uv run python -m tailor bank lint`.

## Bullets vs. context

- **Bullets** are printable, owner-approved statements. Each one is a complete accomplishment: verb + what + how + result/scale.
- **Context** items are facts that are never printed but that rewrites may draw on: team size, her exact role, the stack, scale, constraints, who used the work, what changed after. A long, honest `context` list is what lets free rewriting stay truthful. **Put more facts in context than in bullets.**
- Phrase ownership precisely in context, e.g. "I wrote the scraper and the eval harness; Alex wrote the frontend", so the guards can catch inflation.

## Stories (for cover letters)

`stories:` holds true anecdotes and motivations (the why-this-field origin, a formative project, a leadership moment). They're never printed on the resume, and they're citable by cover letters only once approved. Phrase them as facts, not prose; the cover-letter stage handles the voice. Keep anything she'd consider private (health, family, relationships, identity) out unless she explicitly asks to include it.

## Good bullet shape

- Start with a verb. Use past tense for ended roles and present tense for current ones. No first person and no fluff ("passionate", "various").
- Concrete nouns: the actual system, data, users.
- A number when it's true and known: scale, latency, accuracy, users, time saved, money.
- At most about 210 characters. Write 1–3 framings of the same work as **separate bullets with different tags** (for example an ML-heavy and a product-heavy version) rather than one bullet trying to do both.

Write plain text. `%`, `$`, `&`, `#`, and `_` are fine as written (`40%`, `$2M`, `R&D`, `C#`), because escaping happens in `render.py`. What the bank must not contain is LaTeX *markup*: backslash commands (`\textbf`), braces, or math mode.

## Tags, skills, strength

- `tags`: lowercase, drawn from the vocabulary in `profiles.yaml` tag weights (for example `ml, data, backend, frontend, ios, infra, research, finance, econ, leadership, product, users, teaching, startup`). Add a new tag only if it's added to the profiles too.
- `skills`: canonical names that exist in `skills[]` or `tech_lexicon.txt`. Every skill you list in `skills[]` needs at least one `evidence` bullet ID.
- `strength` (1–5) is her call. Suggest one with a one-line reason, and let her confirm.
- `min_keep: true` is rare. Use it for the 1–2 bullets per entry that should never be dropped.

## Mining a codebase (when asked)

Read without changing anything. Gather **facts, not prose**:
1. README, docs, `pyproject` / `package.json` / `Package.swift`: purpose and stack.
2. The git log for her author email: date range, rough share of commits (`git shortlog -sne`), and big features she wrote.
3. Scale evidence: dataset sizes in configs, SLURM scripts (GPUs, hours), test counts, CI, deployment targets (Vercel, App Store).
4. Anything user-facing: URLs, TestFlight, users mentioned in issues.

Write the findings as **proposed context items**, each with where it came from (`# from: repo/path or git log`), plus a list of **open questions** for the interview. Never copy private code, secrets, or other people's names into the bank.

## Interview (when asked)

Go one experience at a time, a few questions per message, and turn the answers into proposed items right away. Question bank:
- What was the goal, and who was it for?
- What exactly did *you* do versus others? How big was the team?
- What did you build or decide that wouldn't have happened without you?
- Numbers: how much data, how many users, how fast or accurate, how much time or money saved, before and after?
- What was hard (a constraint, a scale problem, ambiguity) and how did you handle it?
- What happened afterward? Is it still used? Who adopted it?
- Which tools or methods, specifically?
- Would you be comfortable defending this bullet in an interview? (If not, soften it.)

End each experience by showing the proposed YAML and asking for approval or edits.
