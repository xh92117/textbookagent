---
name: multi-search-engine
description: Use for web search during textbook planning/writing. Searches public search-engine result pages through web_fetch, not Bocha or LinkAI web_search.
triggers:
  - web search
  - 搜索资料
  - 检索资料
  - 查找参考资料
  - 课程标准
  - 最新资料
allowed-tools:
  - web_fetch
  - knowledge_capture
---

# Multi Search Engine

Use this skill whenever a textbook task needs current public references, curriculum standards, examples, statistics, documentation, diagrams, case studies, or image/reference sources.

This skill follows the ClawHub `gpyangyoujun/multi-search-engine` pattern: choose a search engine by language and fetch the search-result page with `web_fetch`. Do not use the legacy Bocha `web_search` tool.

## Search Workflow

1. Decide the query language.
   - Chinese topics: prefer Baidu or Bing China.
   - English/international technical topics: prefer Bing, Google, DuckDuckGo, or Brave.
2. Build 2-4 targeted queries, not one broad query.
3. Fetch search result pages with `web_fetch`.
4. Open the most relevant result URLs with `web_fetch`.
5. Extract only high-signal facts: definitions, constraints, examples, data, dates, standards, and source URLs.
6. For each original source page that is credible, relevant, and reusable, call `knowledge_capture` to save it into `knowledge/<book_id>/sources` when a `book_id` is known, or `knowledge/sources` otherwise. Do not save Google/Baidu/Bing result pages.
7. Write a compact evidence pack for downstream textbook writing.

## Search URLs

Use URL-encoded queries.

- Bing: `https://www.bing.com/search?q=<query>`
- Google: `https://www.google.com/search?q=<query>`
- DuckDuckGo: `https://duckduckgo.com/html/?q=<query>`
- Brave: `https://search.brave.com/search?q=<query>`
- Baidu: `https://www.baidu.com/s?wd=<query>`

If one engine fails or returns noisy content, try another engine.

## Evidence Pack Format

Return this structure to the writing agent:

```markdown
## Web Evidence Pack

### Query Plan
- Query 1: ...
- Query 2: ...

### Useful Sources
1. Title - URL
   - Relevant facts:
   - How to use in chapter:

### Writing Notes
- Definitions or standards to cite:
- Data/examples to transform into figures:
- Image or diagram opportunities:
- Reliability cautions:
```

## Constraints

- Prefer primary sources, official docs, standards, papers, university course pages, and reputable publishers.
- Do not copy long passages. Paraphrase and keep source URLs.
- For textbook chapters, use search results to enrich content with grounded examples, not to inflate prose.
- Save only durable, high-value pages with `knowledge_capture`; skip duplicates, thin pages, ads, and search-result pages.
- If search fails, explicitly say which engine failed and continue with available local knowledge.
