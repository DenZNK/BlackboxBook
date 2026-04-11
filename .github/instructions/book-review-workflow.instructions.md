---
name: "BlackboxBook Review Workflow Rules"
description: "Use when editing BlackboxBook review agents, prompts, and persistent review-cache files in .github/. Covers cache-first review flow, repository logging, staleness rules, and direct-orchestrator compatibility."
applyTo: ".github/**/*.md"
---
# BlackboxBook Review Workflow Rules

Use these rules when editing review agents, prompts, or persistent review-cache files under `.github/`.

## Cache-First Review Design

- Treat `.github/review-cache/` as the cross-run source of truth for prior research. Session memory is only the run-local scratchpad.
- Before adding any new web-backed review logic, make the workflow inspect the repo cache first: `source-registry.md`, `scope-log.md`, and only the relevant topic files in `.github/review-cache/topics/`.
- Every factual workflow must choose one cache action per topic: `reuse_cache`, `refresh_watch_sources`, or `research_from_scratch`.
- `reuse_cache` is the default when the topic file is still fresh and already covers the claims in scope.
- `refresh_watch_sources` means re-checking only the canonical watch sources already logged for that topic. Do not broaden to new sources unless those watch sources changed or no longer cover the claim.
- `research_from_scratch` is allowed only when the topic is missing from cache, the manuscript now makes a materially different claim, or the cached topic is too incomplete to support the request.

## Persistent Logging Requirements

- Log canonical sources in `.github/review-cache/source-registry.md` with stable `Source ID`s, freshness class, and last-checked date.
- Log review scope coverage in `.github/review-cache/scope-log.md` so future runs know what chapters, sections, or cross-book topics were already checked.
- Keep reusable factual summaries in topic files under `.github/review-cache/topics/`.
- Topic files must record `Last verified`, `Next scheduled review`, refresh triggers, watch source IDs, canonical source IDs, cached conclusions, and known unknowns.
- When research confirms that nothing changed, still update the relevant `Last checked` or `Last verified` fields so later runs can skip redundant fetches.

## Freshness And Scope

- Use freshness classes to control rechecks: `static`, `slow`, `fast`, `volatile`.
- Re-check old sources only when the freshness window has expired, a watch source indicates change, the user explicitly asks for the latest state, or the manuscript scope changed enough that the old cache no longer covers the claim.
- Direct orchestrator requests such as adding a topic, fixing one chapter, or follow-up corrections must use the same cache-first protocol. Do not force a full-book plan when the request is scoped.
- Scoped follow-up requests should read only the impacted topic files and the minimal adjacent chapter or navigation context needed for quality.

## Converting Findings Into Book Updates

- When research or fact-checking shows that the manuscript teaches an outdated, superseded, or materially weaker approach and a better source-backed approach is available, the workflow must produce a concrete manuscript delta for the affected chapter(s), not just a cache refresh or finding note.
- Findings, chapter briefs, and edit handoffs should carry enough detail to update the relevant prose, `Практический вывод`, and `Источники` blocks.
- Keep this behavior explicit in `.github/agents/` and `.github/prompts/` so direct agent invocations inherit the same update policy.

## Editing Discipline

- Keep the repo-cache schema simple and stable. Prefer additive updates to rewriting large files.
- Preserve stable IDs (`Finding ID`, `Topic ID`, `Source ID`, `Scope ID`) so findings and cache records can be reconciled across runs.
- When editing agents or prompts, put the cache-first behavior in the agent itself, not only in a single prompt, so direct user invocations stay consistent.
