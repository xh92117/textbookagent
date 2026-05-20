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
2. Search with Brave first only while Brave has not failed in the current task. Use a single Brave probe query first; do not fire multiple Brave queries in parallel:
   - `web_fetch({"url":"https://search.brave.com/search?q=<url-encoded-query>"})`
3. If Brave returns HTTP 429, captcha, verification, or another blocked result, mark Brave as unavailable for the rest of this task. Do not call Brave again for later queries in the same task, including parallel batches.
4. If Brave is unavailable or fails for a query, try Bing once using English terms and locale hints:
   - `web_fetch({"url":"https://www.bing.com/search?q=<url-encoded-query>&cc=us&setlang=en"})`
5. If both Brave and Bing fail, stop using search engines and fetch known source URLs directly: official docs, standards, papers, GitHub repository contents APIs, university pages, and reputable publishers.
6. Do not try Google, Baidu, or DuckDuckGo repeatedly in this environment. They often return redirect, safety-verification, or challenge pages through `web_fetch`; treat those as failed engines and move on.
7. After at most one useful search-result page per query, open the most relevant original source URLs with `web_fetch`. Prefer known high-quality source URLs directly when search engines are blocked.
8. For every credible original source page, immediately call `knowledge_capture` before starting another search batch. Do not postpone saving until the end; long search sessions may be compacted. If `knowledge_capture` skips a concise but useful source as too short, do not keep searching only to satisfy the save guard; keep the source in the evidence pack and continue.
9. Extract only high-signal facts: definitions, constraints, examples, data, dates, standards, and source URLs.
10. Save 3-6 durable sources per chapter-writing pass and 6-12 durable sources per broad textbook research pass unless the user asks for more. Do not keep searching after enough high-quality sources have been saved or fetched.
11. For each original source page that is credible, relevant, and reusable, call `knowledge_capture` to save it into `knowledge/<book_id>/sources` when a `book_id` is known, or `knowledge/sources` otherwise. Do not save Google/Baidu/Bing/Brave/DuckDuckGo result pages.
12. Keep a short progress ledger of attempted queries, failed engines, fetched source URLs, and saved knowledge files. If context is compacted, continue from that ledger instead of restarting the search workflow.
13. Write a compact evidence pack for downstream textbook writing.

## Search URLs

Use URL-encoded queries.

- Primary in this runtime: Brave `https://search.brave.com/search?q=<query>` until the first HTTP 429/block/challenge, then disable it for the task.
- Fallback: Bing `https://www.bing.com/search?q=<query>&cc=us&setlang=en`
- Direct source fallback: official docs, standards, papers, GitHub contents API endpoints, university pages, and reputable publishers.
- Avoid unless explicitly requested: Google `https://www.google.com/search?q=<query>`
- Avoid unless explicitly requested: Baidu `https://www.baidu.com/s?wd=<query>`
- Avoid unless explicitly requested: DuckDuckGo `https://duckduckgo.com/html/?q=<query>`

The default order for this project is Brave -> Bing -> direct known source URLs. Do not spend more than one failed attempt per engine per query, and do not reuse an engine after it has been rate-limited in this task.

## Evidence Pack Format

Return this structure to the writing agent:

```markdown
## Web Evidence Pack

### Query Plan
- Query 1: ...
- Query 2: ...

### Search Attempts
- Query 1: Brave/Bing/direct-source status; failed engines marked unavailable.
- Query 2: Brave/Bing/direct-source status; failed engines marked unavailable.

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
- Save immediately after each useful source fetch. A source is not considered completed until `knowledge_capture` has returned saved/existing.
- If search fails, explicitly say which engine failed and continue with available local knowledge.
