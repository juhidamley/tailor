---
name: tailor
description: Use when Juhi asks to tailor her resume to a specific job from inside Claude Code (/tailor, "tailor my resume for this listing", or pasting a job URL or description). Runs the resume-tailor CLI on the listing, then walks her through the report, flags, and gaps. Requires M5 or later to be built.
---

# /tailor: run a tailoring job from Claude Code

This skill drives the **built tool**. It does not hand-edit a resume.

## Steps

1. **Get the listing.**
   - If she pasted text, write it to `applications/_inbox/<timestamp>.txt`.
   - If she gave a URL, try to fetch the page text. LinkedIn, Workday, and other login-walled or JavaScript-heavy pages often fail. If the fetch fails or returns less than about 300 characters, ask her to paste the description or use the extension.
   - Show her the first few lines and the detected title and company, and confirm it's the right listing.

2. **Pick the options.** Ask which profile to use (`swe_ml`, `fde`, `pm`, `research_quant`, or auto) and whether she wants a cover letter, unless she has already said.

3. **Run it:**
   ```bash
   uv run python -m tailor run applications/_inbox/<file>.txt --profile <p> [--cover-letter]
   ```
   This takes about 1–3 minutes, mostly `claude -p` calls. If it fails, show the typed error message, along with the fix if it's a known one (Tectonic missing, Claude Code not signed in, bank invalid).

4. **Review the result with her.** Read `report.md` and `run.json` from the run folder and summarize:
   - the profile used and the page fill
   - **must-haves not covered**, split into "not in bank" (possible gaps in her experience or in the bank) and "dropped for space" (bullets that could be swapped in)
   - every **revert** and **verifier flag**, showing the source text next to the rejected rewrite
   - 2–3 bullets that changed most from their source, so she can check that the voice still sounds like her

5. **Offer adjustments**, re-running rather than hand-editing the .tex:
   - a different profile
   - pinning a bullet (`--pin <id>`) or excluding one (`--exclude <id>`), if those options exist; if they don't, note them as feature requests
   - for gaps marked "not in bank", offer to use the **bank-authoring** skill to add material she actually has

## Don'ts

- Don't edit `resume.tex` or the PDF by hand. A manual edit skips the guards.
- Don't add anything to the bank in this flow unless she asks and approves it.
- Don't submit applications or fill in forms.
