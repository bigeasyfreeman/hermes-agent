---
name: reading-pack-builder
description: Build a self-contained local HTML reading pack from a pile of local documents, with an index, deliberate reading order, one-at-a-time navigation, summaries, and local read/unread progress. Use when Eric asks for a reading pack or has multiple docs to review.
---

# Reading Pack Builder

## First-Run Interview

Before writing a pack, ask for:

- Where reading packs should be saved.
- Visual preferences, unless an html-artifacts/design skill or existing project style is available.

If no preference is known, default only after saying the default: a quiet, dense, local HTML pack under `HERMES_HOME/artifacts/reading-packs/<slug>/`.

## Inputs

Require three or more local documents unless Eric explicitly asks for a smaller pack. Supported sources may include Markdown, text, HTML, PDF, DOCX, CSV, and code-adjacent docs. If a format needs a converter, use the repo or system tool that preserves structure best.

## Workflow

1. Inventory source documents and preserve absolute source paths in metadata.
2. Convert each document to clean HTML while preserving headings, lists, tables, links, code blocks, and source structure.
3. Write one page per source document.
4. Create an index page with:
   - title,
   - one-line summary,
   - source path,
   - suggested reading order,
   - reasoning for the order,
   - read/unread state.
5. Add previous/next navigation to each page.
6. Store progress locally so the pack works offline. Prefer `localStorage`; if a file-backed progress script is needed, keep it optional and documented.
7. Open or provide the local `index.html` path after building.

## Reading Order

Order by comprehension, not filename:

1. Orientation or strategy docs.
2. Design decisions and specs.
3. Implementation details.
4. Evidence, appendices, logs, or examples.
5. Contradictory or dissenting material where it will be easiest to evaluate.

If the best order is uncertain, explain the uncertainty in one sentence.

## Offline Requirement

The pack must work as local files without a server:

- Inline CSS and JavaScript.
- Avoid external fonts, CDNs, trackers, or remote assets.
- Copy local images/assets into the pack if needed.
- Use relative links.

## Output

After creation, report:

- Pack path.
- Source count.
- Suggested order.
- Any conversion degradation.
- How progress is stored.
