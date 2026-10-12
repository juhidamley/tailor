---
name: chrome-extension-mv3
description: Use when working in extension/: the MV3 manifest, side panel, listing extractors (LinkedIn, Greenhouse, Lever, Ashby, Workday, generic), talking to the localhost server with a token, streaming progress, and extractor fixture tests.
---

# Chrome extension (MV3)

## Manifest essentials

```json
{
  "manifest_version": 3,
  "name": "resume-tailor",
  "action": { "default_title": "Tailor resume" },
  "side_panel": { "default_path": "sidepanel.html" },
  "background": { "service_worker": "background.js", "type": "module" },
  "permissions": ["sidePanel", "activeTab", "scripting", "storage"],
  "host_permissions": ["http://127.0.0.1:8765/*"],
  "options_page": "options.html"
}
```

- In `background.ts`, call `chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })`.
- There's no `content_scripts` block. Inject on demand with `chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] })`. `activeTab` grants access only after the user clicks the action. If the side panel was opened earlier and the tab has changed, show a "Click the toolbar icon to read this page" state rather than requesting broad host permissions.
- Pin a stable extension ID by putting a `key` in the manifest (generate it once and keep it in the repo). The server's CORS allowlist needs a fixed `chrome-extension://<id>` origin.

## Where network calls happen

- **Only the side panel or the service worker talks to the server.** Never the content script: content scripts run under the page's origin, so CORS and the site's CSP apply to them.
- Extension pages with a matching `host_permissions` entry can fetch `http://127.0.0.1:8765` directly. The server still checks `Origin` and `X-Tailor-Token`.
- The content script only extracts and returns a plain object through the `executeScript` result.

## Progress stream: don't use `EventSource`

`EventSource` can't send custom headers, so it can't send `X-Tailor-Token`. Never put the token in the URL. Read the SSE stream with `fetch` and a small parser instead:

```ts
const res = await fetch(`${BASE}/runs/${id}/events`, { headers: { "X-Tailor-Token": token } });
const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
let buf = "";
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  buf += value;
  let i;
  while ((i = buf.indexOf("\n\n")) >= 0) {
    const frame = buf.slice(0, i); buf = buf.slice(i + 2);
    const ev = parseSseFrame(frame);       // handles event:, data: (multi-line), id:
    if (ev) onEvent(ev);
  }
}
```

Reconnect once on a network error, using `GET /runs/{id}` to resync the state. The side panel may be closed and reopened mid-run, so store the active `run_id` in `chrome.storage.session` and resume from it.

## Listing extraction (content.ts)

Try these in order, and return `{ title, company, location, text, url, source }`, where `source` records which method succeeded:

1. **The user's selection.** Use it if `window.getSelection()` has more than about 200 characters.
2. **JSON-LD `JobPosting`.** Look in `script[type="application/ld+json"]`, including inside `@graph` arrays. Greenhouse, Lever, Ashby, many Workday tenants, and LinkedIn guest pages often include it. `description` is HTML, so convert it to text.
3. **Site extractor**, chosen by hostname:
   - `linkedin.com/jobs`: the description container on the job details pane. LinkedIn's class names change often, so try a list of selectors and keep the list in one place.
   - `boards.greenhouse.io` / `job-boards.greenhouse.io`: the main job content container.
   - `jobs.lever.co`: the posting page sections.
   - `jobs.ashbyhq.com`: a single-page app, so wait for the description node (MutationObserver, 5s timeout).
   - `*.myworkdayjobs.com`: a single-page app. Workday uses stable `data-automation-id` attributes (for example the job posting description and title), so prefer those over classes.
4. **Generic:** run `@mozilla/readability` on `document.cloneNode(true)`.

Selectors here are best guesses that drift over time. **Verify each one against a real saved page** before adding it, and keep the saved HTML as a fixture.

HTML to text: keep list items as `- ` lines and paragraphs as blank-line breaks, collapse whitespace, and drop "Apply" buttons, EEO boilerplate, and benefits sections, which are recognizable by heading. Cap the result at about 20k characters.

If the result is shorter than about 300 characters, set `low_confidence: true` so the UI asks the user to check it or paste the listing.

## Side panel UX

- States: `server-down` (with a help line: "Start the server: make serve") → `idle` → `extracted` (editable textarea, profile dropdown, cover-letter checkbox) → `running` (stage list with ticks, from SSE) → `done` (Open PDF, Download .tex, report rendered) or `error` (the server's human-readable message plus Retry).
- Keep the textarea editable always. The extraction is a suggestion.
- Recent runs: `GET /runs`, showing the last 10, each with company, role, date, and Open.
- Open PDFs with `chrome.tabs.create` on a blob URL made from an authenticated fetch. A plain link would drop the token.

## Options page

The options page holds the server URL (default `http://127.0.0.1:8765`) and the token, stored in `chrome.storage.local`, plus a "Test connection" button that calls `/health`.

## Tests

- Use Vitest with jsdom. Each extractor gets `tests/fixtures/<site>/*.html`, saved from real pages with personal data stripped, plus an expected `title`, `company`, and a description prefix.
- Add a JSON-LD test with `@graph` and with an HTML description.
- Test the SSE parser with multi-line `data:`, frames split across chunks, and comments (`:`).
