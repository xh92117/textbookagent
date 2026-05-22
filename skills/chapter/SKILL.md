---
name: textbook-chapter
description: Use when the user requests writing, continuing, or rewriting a specific chapter. Supports chart requirement identification and anti-AI-tone writing.
triggers:
  - 编写第
  - 写第
  - 续写章节
  - 重写章节
  - 编写章节
allowed-tools:
  - read
  - write
  - bash
  - web_fetch
  - knowledge_capture
---

# Chapter Writing

Write textbook chapter content based on the outline, context, and project-level WritingSpec. The WritingSpec defines audience, learning orientation, content ratio, chapter structure, visual policy, language policy, and word-count policy. Follows anti-AI-tone rules strictly.

## 核心指令

1. **上下文准备**: 读取大纲、前章摘要、术语表，构建写作上下文。
2. **章节结构**: 优先服从 WritingSpec.chapter_structure。不要把某一本教材、某一种受众或某一种学科当作默认模板。
3. **图表需求识别**: 正文中需要图表时，使用标记：
   - `[图表: 折线图，展示XXX趋势]` → 可用代码生成的数据图表
   - `[插图: XXX示意图]` → 需要AI生成的插图
4. **去AI味铁律**: 严格遵守去AI味规则，禁止使用"值得注意的是""综上所述"等AI常用语。
5. **内容比例**: 按 WritingSpec.content_ratio 控制理论、案例、流程、实践和代码比例；如果 WritingSpec 限制代码比例，代码只作为必要工具示例。
6. **习题设计**: 按 WritingSpec 和认知层次设计习题；题型可以随教材定位变化。
6. **保存章节**: 写入章节文件，更新章节摘要。

状态管理：编写过程中维护 `chapter_XXX.md` 和更新 `chapter_summaries.md`。

## 工作流示例

### 示例1：编写新章节
- **用户输入**: "编写第3章 栈与队列"
- **模型思考**: 需要读取大纲了解第3章定位，读取前章摘要保证衔接，读取术语表保证一致。
- **模型行动**:
  1. `read("outline.md")` 确认第3章结构和要求
  2. `read("chapters/chapter_002.md")` 读取前章内容
  3. `read("<base_dir>/templates/chapter_template.md")` 读取章节模板
  4. `read("<base_dir>/templates/anti_ai_rules.md")` 读取去AI味规则
  5. 按模板结构编写章节
  6. `write("chapters/chapter_003.md", content)` 保存

### 示例2：重写章节
- **用户输入**: "第5章写得太浅了，重写一下，加深难度"
- **模型思考**: 读取现有第5章，分析不足，按更高认知层次重写。
- **模型行动**:
  1. `read("chapters/chapter_005.md")` 读取现有内容
  2. 调整认知层次分布，增加分析和评价层次内容
  3. `write("chapters/chapter_005.md", new_content)` 覆盖保存

## Tool Usage Specification

- `read`: Read outline, previous chapters, terminology, and templates
  - Chapter template: `read("<base_dir>/templates/chapter_template.md")`
  - Anti-AI rules: `read("<base_dir>/templates/anti_ai_rules.md")`
- `write`: Write chapter file
  - Syntax: `write("<file_path>", "<content>")`
- `bash`: Execute sandbox for chart generation (used with sandbox skill)
- `web_fetch`: Fetch search result pages and source pages through the multi-search-engine skill
- `knowledge_capture`: Save useful, reusable web source pages into the knowledge source directory

## Output Specification

Report the following upon completion:
1. Chapter number and title
2. Word count
3. Identified chart requirements ([图表:...] and [插图:...] markers)
4. Exercise count and type distribution
5. Chapter file path

## Constraints

- Word count must follow WritingSpec.word_count_policy; do not treat raw character count, token count, JSON, Markdown syntax, code blocks, or visual markers as正文有效字数.
- Anti-AI-tone language is mandatory (see anti_ai_rules.md)
- Terminology must be consistent with the terminology table
- Code examples must be runnable when used, but code volume must follow WritingSpec.
- All code examples must be wrapped in fenced code blocks such as ```python ... ```. Never leave bare code lines in chapter Markdown; keep `#` comments inside the fence so Word export does not treat them as headings.
- Exercises must match the textbook audience and learning orientation.
- Chart markers must use standard format: `[图表: ...]` or `[插图: ...]`

## Required Enrichment Pass

Before writing a chapter, run an enrichment pass unless the user explicitly says not to use external material.

Hard stop rules:
- Run at most one enrichment pass per chapter-writing request.
- If the context already contains 3+ relevant knowledge chunks, 2+ credible web sources, or a previous Web Evidence Pack, stop searching and write the chapter.
- If any search engine returns HTTP 429/block/challenge, mark that engine unavailable and do not retry it in this chapter request.
- Do not reread this skill, the multi-search skill, or chapter templates after they have already been read in the current request; continue from the compact state board.
- After reading enough source material, the next action must be `write` for the chapter draft, not another search/list/read cycle.

1. Use the `multi-search-engine` skill with `web_fetch` to build a small Web Evidence Pack for the chapter topic. Do not use Bocha `web_search`.
   - When a fetched original source is credible and reusable for future chapters, save it with `knowledge_capture` and include why it is useful.
   - Do not save search-result pages or low-signal pages.
2. Read the LLM-WIKI knowledge base under `knowledge/_llm_wiki/` when present:
   - `index.json` contains `chunks` with `summary`, `use_when`, `keywords`, and `content_type`.
   - Select chunks by matching the chapter objective/key concepts against `use_when` and `keywords`.
   - Read only the most relevant chunk Markdown files from `_llm_wiki/chunks/`; do not dump the whole knowledge base into context.
3. Add at least one grounded example, case, standard, dataset idea, or recent reference from the evidence pack.
4. Add visual asset requirements:
   - Use `[图表: ...]` for data, process, comparison, or relationship visuals that sandbox Python can generate.
   - Use `[插图: ...]` for conceptual scenes, architecture diagrams, equipment, or explanatory illustrations that the imagegen skill can generate.
5. When a chart needs data, either derive a small didactic dataset from the chapter context or cite the source in the Web Evidence Pack.

The final chapter should feel researched and concrete, not only conceptual exposition.
