---
name: latex-resume-template
description: Use when creating or editing server/templates/*.tex.j2, the escaping in render.py, or compile.py. Covers Jake's-Resume-style LaTeX through Jinja2, compiling and debugging with Tectonic, ATS text-layer checks, and measuring page fill.
---

# LaTeX resume template (Jinja2 + Tectonic)

## Jinja environment (render.py)

Use LaTeX-safe delimiters, so Jinja never collides with braces:

```python
env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
    block_start_string=r"\BLOCK{", block_end_string="}",
    variable_start_string=r"\VAR{", variable_end_string="}",
    comment_start_string=r"\#{", comment_end_string="}",
    trim_blocks=True, lstrip_blocks=True,
    autoescape=False,
    undefined=jinja2.StrictUndefined,   # a missing field raises; it never renders blank
    keep_trailing_newline=True,
)
env.filters["tex"] = escape_tex
```

Do **not** set `line_statement_prefix="%%"` or `line_comment_prefix`. LaTeX comment lines would then be parsed as Jinja.

Every value that comes from the bank or the model goes through `|tex`: `\VAR{b.text|tex}`. A bare `\VAR{x}` is allowed only for values in `RAW_ALLOWLIST` in render.py, which are numbers that geometry code builds, like `font_size`. A test greps the templates for `\VAR{` without `|tex` that isn't on the allowlist.

## Escaping: one function, one pass

Use a single `re.sub` over a character class with a lookup dict, so nothing gets escaped twice:

| char | output |
|---|---|
| `\` | `\textbackslash{}` |
| `& % $ # _ { }` | `\& \% \$ \# \_ \{ \}` |
| `~` | `\textasciitilde{}` |
| `^` | `\textasciicircum{}` |

Tectonic is XeTeX-based and reads UTF-8. Leave curly quotes, en and em dashes, and accented letters as Unicode, and use a font that has them (Latin Modern via `fontspec`, or TeX Gyre).

**Round-trip test (required):** for each of `C#`, `R&D`, `50%`, `$2M`, `snake_case`, `~3x`, `a^2`, `{json}`, `back\slash`, `naïve`, and `“quoted”`, render a one-bullet document, compile it, extract the text with pdfplumber, and assert that the original string appears. Whitespace normalization is allowed.

## Jake's Resume structure

Keep the standard macros: `\resumeSubheading{org}{dates}{role}{location}`, `\resumeProjectHeading{title}{dates}`, `\resumeItem{text}`, `\resumeSubHeadingListStart/End`, and `\resumeItemListStart/End`. Use a single column, section rules through `titlesec`, and no nested tables.

**XeTeX caveat:** the original uses pdfTeX-only primitives. Guard them:

```latex
\ifdefined\pdfgentounicode
  \input{glyphtounicode}\pdfgentounicode=1
\fi
```

XeTeX writes a Unicode text layer natively, so ATS parsing still works.

Expose `font_size`, `margin_in`, and `item_sep` as template variables, so `fit.py` can adjust them within the bounds in config. Section order comes from the profile's `section_order`. Loop over it in the template; don't hard-code the order.

## Compiling (compile.py)

Run `tectonic --help` first, because V1 and V2 interfaces differ (`tectonic file.tex` versus `tectonic -X compile file.tex`). The behaviors you need are:
- an output directory set to the run dir
- keeping logs
- **no shell-escape, ever**

The first compile downloads packages into Tectonic's cache, which is slow. Later compiles are fast and work offline. `make check` should warm the cache.

To debug a failed compile:
1. Open `resume.log` and find the **first** `!` line. Everything after it is usually a cascade.
2. `Missing $ inserted` or `Undefined control sequence` almost always means an unescaped `_ ^ \` got through. Fix `escape_tex` or add the missing `|tex`. **Never patch a rendered .tex.**
3. `Overfull \hbox` is a warning, but long unbreakable tokens such as URLs or identifiers can run into the margin. Use `\href`, and enforce the character budget in rewrite.

Raise `CompileError(first_error_line, context_lines)`.

## Page count and fill

- Pages: `len(pypdf.PdfReader(path).pages)`.
- Fill: open page 1 with pdfplumber. Take the largest `bottom` over `extract_words()` and divide by (page height − bottom margin in points). The fit target is exactly one page with fill ≥ 0.88.

## ATS sanity check (in tests and in `render --all`)

Extract the text with pdfplumber and assert that:
- the reading order is name → contact → sections, in profile order
- no `(cid:` sequences appear (that indicates a font encoding problem)
- the email and URLs come through intact
- each section heading appears exactly once
