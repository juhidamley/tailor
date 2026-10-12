---
name: fact-guards
description: Use when writing or changing server/tailor/guards/ (factdiff.py, verifier.py, tech_lexicon.txt), the repair loop, or their tests. It defines what counts as a new claim, how numbers and terms are normalized, the verifier rubric, and the adversarial test catalog.
---

# Fact guards

These guards are the reason the tool can rewrite freely without lying. The rule: **a generated bullet may contain only facts that appear in its own cited sources** (bank bullets and `context` items whose IDs are in `source_ids`). Never compare against the whole bank, the listing, or the other bullets in the same entry.

## Pipeline per bullet

```
rewrite ──► resolve source_ids ──► factdiff ──► verifier ──► pass
                 │ unknown id            │ hard_fail      │ overclaim/unsupported
                 ▼                       ▼                ▼
              hard_fail ───────────► repair once (feedback) ──► guards again ──► fail → fallback to source text
```

- An empty `source_ids`, or an ID that doesn't resolve, is a **hard_fail** before extraction even starts.
- If the factdiff result is a hard_fail, skip the verifier on that attempt to save a call. Go straight to repair.
- Fallback means the **original text** of the highest-scored cited *bullet* (context items are never printed). If only context items were cited, drop the bullet entirely and record that.

## factdiff.py: extraction

All extractors take a string and return a set of normalized tokens. Compare `extract(rewrite) - extract(union(sources))`.

### Numbers → hard_fail if new
Normalize each number to a canonical `(value, unit)` pair:
- `40%`, `40 percent`, and `forty percent` → `(40, "%")`. Spell out the words zero through twenty, plus the tens.
- `$2M`, `$2 million`, and `$2,000,000` → `(2000000, "$")`. Handle the `k`/`K`, `M`/`mm`, and `B`/`bn` suffixes.
- `3x`, `3×`, and `3-fold` → `(3, "x")`.
- `2M rows` and `2,000,000 rows` → `(2000000, "")`. Unitless numbers compare by value only.
- Approximations: `~50`, `about 50`, `50+`, and `over 50` all become `(50, …)` with a qualifier. A **rewrite that drops a qualifier** (source "~50", rewrite "50") is a soft_flag (added certainty). **Adding** one is fine.
- Ranges: `10–20` → both endpoints.
- Years (1990–2039) and month-year dates are extracted separately, as `date` tokens. A new date is a hard_fail.
- Ignore the digits inside tech names (`Python 3`, `S3`, `GPT-4`, `ES6`) by stripping lexicon matches *before* number extraction.

### Tech and skill terms → hard_fail if new
- Build the lexicon from every bank `skills[].items[].name` plus `tech_lexicon.txt`, which has one line per canonical term and comma-separated aliases, e.g. `Kubernetes, k8s, kube`.
- Match case-insensitively on word boundaries, **longest match first** (so `scikit-learn` matches before `scikit`, and `Google Cloud Platform` before `Google`). Map each match to its canonical form.
- Handle `C++`, `C#`, `.NET`, and `Node.js`. These break naive `\b` regexes, so use explicit lookarounds: `(?<![\w+#.])TERM(?![\w+#])`.

### Proper nouns → soft_flag if new
- These are capitalized tokens, or runs of them, that are not sentence-initial, not in the lexicon, and not in `COMMON_CAPS`, a stoplist of resume verbs and generic words (Led, Built, API, ML, AI, the month names, US, and so on).
- They are sent to the verifier as notes. A new org or customer name is a common way hallucinations creep in.

### Scope and ownership words → soft_flag if new
Use a curated list grouped by strength:
- Ownership: `led, managed, owned, directed, headed, spearheaded, founded, co-founded, architected, sole, solely, single-handedly, independently, end-to-end`
- Team size: `team of N`, `N engineers`, `N-person`
- Outcomes: `increased, reduced, improved, saved, grew, drove` followed by a quantity

A soft_flag is raised when the rewrite has a word from a group the sources don't. Special case: if the sources contain `team`, `we`, `with`, `helped`, `contributed`, `assisted`, or `supported`, and the rewrite uses an ownership word, **escalate it to hard_fail**. That is the classic "helped" → "led" inflation.

### Output model
```python
class FactDiffResult(BaseModel):
    bullet_index: int
    hard_fails: list[Finding]   # Finding(kind, token, detail)
    soft_flags: list[Finding]
    @property
    def passed(self) -> bool: return not self.hard_fails
```

## verifier.py

The verifier runs as a separate LLM call, through the same `LLM` interface, with prompt `prompts/verifier.md`. It must never see the rewrite prompt or the JobSpec, because a verifier that knows the target job tends to rationalize keyword stuffing.

Its input is a numbered source list (ID and text), the rewrite, and the factdiff soft flags as "points to check". It returns:
```json
{"verdict": "supported|overclaim|unsupported", "issues": ["..."], "suggested_fix": "..."}
```

Rubric for the prompt. A rewrite is **overclaim** if it:
1. raises the role or ownership level
2. turns team work into individual credit
3. adds an outcome, impact, or causal claim ("which led to…") not in the sources
4. removes hedges or approximations
5. changes the timeframe or tense to imply something ongoing
6. implies a method, tool, or scale not stated

It is **unsupported** if any substantive claim has no basis at all. Rewording, reordering, using the listing's vocabulary for the *same* fact, and merging sources are all fine.

Tell the verifier to judge strictly but literally: synonyms are fine, new information is not. Batch every bullet of one entry into one call (as an array) to cut latency, but judge each bullet on its own.

## Repair prompt

The repair prompt is the rewrite prompt plus a "Previous attempt was rejected" block that lists the exact findings (`new number: 40%`, `ownership escalation: helped→led`). Instruct the model to remove or soften the claim, not to find a different justification for it.

## Adversarial test catalog (tests/test_factdiff.py, tests/test_guards_redteam.py)

Each case gives the sources, the rewrite, and the expected result. At minimum, cover these:

| # | Case | Expected |
|---|---|---|
| 1 | Pure rewording, same facts | pass |
| 2 | `40%` → `40 percent` | pass |
| 3 | `$2M` → `$2,000,000` | pass |
| 4 | New `35%` | hard: number |
| 5 | A number from a *different* bullet of the same entry, not cited | hard: number |
| 6 | Citing both bullets, then using that number | pass |
| 7 | `~50 users` → `50 users` | soft: certainty |
| 8 | `about 50` → `over 50` | soft: certainty |
| 9 | Adds `Kubernetes` | hard: tech |
| 10 | Source has `k8s`, rewrite has `Kubernetes` | pass (alias) |
| 11 | Source `C`, rewrite `C++` | hard: tech |
| 12 | `scikit-learn` vs `sklearn` | pass (alias) |
| 13 | Source `helped build`, rewrite `Led` | hard: escalation |
| 14 | Source `built`, rewrite `Architected` | soft: scope |
| 15 | Adds `team of 5` | hard: number + soft: scope |
| 16 | Adds a customer name `Acme Corp` | soft: proper noun |
| 17 | Adds the year `2025` | hard: date |
| 18 | `Python 3` present in both | pass (no stray `3`) |
| 19 | `GPT-4` in the source, rewrite says `GPT-4o` | hard: tech |
| 20 | Empty `source_ids` | hard |
| 21 | An unknown source ID | hard |
| 22 | Only context items cited, rewrite consistent with them | pass |
| 23 | Rewrite fails twice | fallback to source text, revert recorded |
| 24 | Only context cited and fails twice | bullet dropped, recorded |
| 25 | `3x faster` → `300% faster` | hard (different claim, don't convert) |

Add more as bugs are found. **Every bug becomes a test case.**

Red-team suite: hand-write 15+ plausible but bad rewrites (inflation, invented metrics, a borrowed number), run them through factdiff plus a **replayed** verifier, and assert every one is caught by at least one guard.
