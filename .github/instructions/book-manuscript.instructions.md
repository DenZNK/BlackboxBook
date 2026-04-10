---
name: "BlackboxBook Manuscript Rules"
description: "Use when editing BlackboxBook chapters in book/. Covers chapter structure, sources, navigation, terminology consistency, and Russian technical manuscript style."
applyTo: "book/**/*.md"
---
# BlackboxBook Chapter Rules

Use these rules for any edit under `book/`.

## Chapter Structure

- Preserve the top-level `#` heading and the chapter's numbered `##` sections.
- Keep the required ending blocks: `Практический вывод`, `Источники`, `Навигация`.
- Preserve `---` separators where they structure the chapter.
- If a chapter gains or loses sections, keep section numbering coherent.
- If a new chapter is created, follow the numeric prefix + snake_case naming pattern.

## Navigation

- Keep previous/next chapter links correct after any structural change.
- If chapter order changes or a new chapter is added, update all affected navigation links.
- Do not leave dangling references to renamed headings or removed files.

## Sources And Factual Claims

- For model families, vendor naming, release status, architecture claims, benchmark claims, and timeline-sensitive statements, use primary sources whenever possible.
- Acceptable source types: official vendor docs or blogs, arXiv papers, official GitHub repositories, benchmark repositories.
- Avoid Medium posts, news rewrites, generic tutorials, and unsourced percentages or forecasts.
- When a claim changes materially, update the `Источники` block accordingly.
- If a table or model-parameter breakdown is used to support a comparison, theme, or argument, keep it populated with actual source-backed data.
- If an important `LLM` or `SLM` must be mentioned but some parameters cannot be verified from primary sources, move that mention into prose with an explicit caveat instead of leaving a partially empty row in the table.

## Style And Terminology

- Write in Russian; keep established English technical terms in English when they are standard in the industry.
- Preserve the book's pattern: analogy -> mechanism -> practical implication -> sources.
- Do not flatten useful analogies into dry textbook prose.
- Keep terminology stable: `LLM`, `attention`, `self-attention`, `MLP`, `MoE`, `SSM`, `Mamba`, `RAG`, `RLHF`, `DPO`, `RoPE`, `BPE`, `KV-кэш`, `context window`, `structured outputs`, `tool use`, `agent loop`, `chain-of-thought`, `test-time compute`, `cross-entropy loss`, `Flash Attention`, `CoVe`, `MCP`, `LDD`.

## Editing Discipline

- Prefer minimal, targeted edits over broad rewrites unless structure is the actual issue.
- Do not remove expressive examples or analogies that still explain the mechanism correctly.
- Do not introduce claims that cannot be verified.
- If a structural gap is real, it is acceptable to add a new section or chapter, but keep the chapter map coherent.
