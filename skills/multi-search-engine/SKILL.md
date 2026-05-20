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

This skill follows the ClawHub `gpyangyoujun/multi-search-engine` pattern: fetch public search-result pages with `web_fetch`. Do not use the legacy Bocha `web_search` or LinkAI search tool.

## Search Workflow

1. Build 2-4 targeted queries, not one broad query.
2. Search with Google first for every query:
   - `web_fetch({"url":"https://www.google.com/search?q=<url-encoded-query>"})`
3. If Google times out, is blocked, returns an HTTP/network error, or yields no useful results, immediately retry the same query with Baidu:
   - `web_fetch({"url":"https://www.baidu.com/s?wd=<url-encoded-query>"})`
4. Only if both Google and Baidu fail, optionally try Bing, DuckDuckGo, or Brave.
5. Open the most relevant result URLs with `web_fetch`.
6. Extract only high-signal facts: definitions, constraints, examples, data, dates, standards, and source URLs.
7. For each original source page that is credible, relevant, and reusable, call `knowledge_capture` to save it into `knowledge/<book_id>/sources` when a `book_id` is known, or `knowledge/sources` otherwise. Do not save Google/Baidu/Bing result pages.
8. Write a compact evidence pack for downstream textbook writing.

## Search URLs

Use URL-encoded queries.

- Primary: Google `https://www.google.com/search?q=<query>`
- First fallback: Baidu `https://www.baidu.com/s?wd=<query>`
- Last-resort fallback: Bing `https://www.bing.com/search?q=<query>`
- Last-resort fallback: DuckDuckGo `https://duckduckgo.com/html/?q=<query>`
- Last-resort fallback: Brave `https://search.brave.com/search?q=<query>`

Do not start with Bing/DuckDuckGo/Brave unless the user explicitly asks for them. The default order is Google -> Baidu -> optional last-resort engines.

## Evidence Pack Format

Return this structure to the writing agent:

```markdown
## Web Evidence Pack

### Query Plan
- Query 1: ...
- Query 2: ...

### Search Attempts
- Query 1: Google success/failure; Baidu fallback used/not used.
- Query 2: Google success/failure; Baidu fallback used/not used.

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
