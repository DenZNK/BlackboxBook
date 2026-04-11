# Persistent Review Cache

This directory is the cross-run cache for BlackboxBook review and source-backed manuscript workflows.

Use it to avoid repeating the same web fetches on every review run or source-backed writing pass. The cache is not only for model/vendor data; it also supports broader factual checks across the book. Session memory still holds run-local raw findings and chapter briefs, but durable research state lives here.

## Files

- `source-registry.md`: canonical primary sources that were already fetched and accepted for review work.
- `scope-log.md`: what chapter, section, or cross-book scope was reviewed, when, and which topic caches it depended on.
- `topics/*.md`: reusable topic summaries with freshness metadata and watch sources.

## Request Handling Algorithm

1. Classify the request as one of: `full-book-review`, `scoped-review`, `improvement-pass`, `topic-addition`, `new-chapter-authoring`, `follow-up-fix`, `structural-request`.
2. Map the request to the smallest relevant set of chapter files and `Topic ID`s, including non-model topics when the claims are about architecture, protocols, safety, evals, serving, observability, or historical context.
3. Read only the relevant topic files plus matching rows in `source-registry.md` and `scope-log.md`.
4. Choose one cache action per topic:
   - `reuse_cache`: the topic file is still fresh and already covers the claims in scope.
   - `refresh_watch_sources`: the topic is stale, the user asked for the latest state, or scope changed slightly. Re-check only the topic's watch sources first.
   - `research_from_scratch`: the topic cache is missing or too incomplete to support the request.
5. Do web fetches only for topics that are missing or stale.
6. After research, update the topic file, `source-registry.md`, and `scope-log.md` before moving on.

## Freshness Classes

| Class | Typical window | Use for |
|---|---|---|
| `static` | no scheduled refresh | foundational papers or concepts that change only if the manuscript scope changes |
| `slow` | 180 days | architecture families, mature papers, long-lived repos |
| `fast` | 30 days | model family naming, vendor docs, API status, release pages |
| `volatile` | 7 days | rapidly changing release status, benchmark leaderboards, pricing-like product surfaces |

These windows are defaults. A topic file may choose a stricter cadence when the chapter is especially time-sensitive.

## Watch-Source-First Rule

- Every topic file should name 1-2 canonical watch sources.
- When a topic becomes stale, re-check those watch sources first.
- If the watch sources are unchanged and still cover the manuscript claim, refresh the cache metadata without broadening the search.
- Add a new source only when a watch source points to it, supersedes an older page, or the manuscript now makes a claim the existing cache does not cover.
- Mark superseded sources in `source-registry.md`; do not silently delete history.

## Direct Orchestrator Requests

The same cache-first flow applies when the user does not run the full-book prompt.

Examples:

- "Add a section about frontier open-weight models" -> classify as `topic-addition`, inspect only the relevant topic files, refresh missing or stale sources, then edit the target chapter.
- "Improve chapter 12 and expand the practical takeaway" -> classify as `improvement-pass`, inspect only the relevant topic files if the rewrite depends on factual claims, then edit the target chapter.
- "Write a new chapter about agent evaluation in production" -> classify as `new-chapter-authoring`, inspect only the relevant topic files and sources needed for the new material, then draft the new chapter and wire navigation.
- "Fix chapter 22 after the last review" -> classify as `follow-up-fix`, inspect the chapter's prior scope-log rows and topic files, and avoid a full-book pass.
- "Re-check only Anthropic naming" -> classify as `scoped-review`, refresh only the Anthropic topic file unless adjacent chapters need confirmation.

## Update Checklist

After any web-backed review or chapter update:

1. Update or create the relevant topic file in `topics/`.
2. Update `source-registry.md` for new, refreshed, or superseded sources.
3. Append or refresh the matching row in `scope-log.md`.
4. Keep raw findings and chapter briefs in session memory for the current run only.

## Who Reads What (Context Budget)

To prevent the orchestrator from exhausting its context window, cache files are read by subagents, not by the orchestrator:

| File | Read by orchestrator? | Read by subagents? |
|---|---|---|
| `scope-log.md` | Yes — for planning only | No (unless needed for scope context) |
| `source-registry.md` | NO — pass path to subagent | Yes — fact-checker, web researcher |
| `topics/*.md` | NO — pass path to subagent | Yes — fact-checker, web researcher |

The orchestrator passes cache file **paths** in delegation prompts. Subagents read the files themselves. The orchestrator never relays file contents between subagents.

After a subagent returns, the orchestrator applies small cache deltas (1–5 line edits to `scope-log.md` and `source-registry.md`) based on the subagent's receipt — without reading the full files.
