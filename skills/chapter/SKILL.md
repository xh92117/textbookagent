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
---

# Chapter Writing

Write textbook chapter content based on the outline and context, including concept definitions, principle explanations, code examples, chart requirement annotations, chapter summaries, and tiered exercises. Follows anti-AI-tone rules strictly.

## 核心指令

1. **上下文准备**: 读取大纲、前章摘要、术语表，构建写作上下文。
2. **章节结构**: 按标准结构编写——导语→正文(分节)→小结→习题。
3. **图表需求识别**: 正文中需要图表时，使用标记：
   - `[图表: 折线图，展示XXX趋势]` → 可用代码生成的数据图表
   - `[插图: XXX示意图]` → 需要AI生成的插图
4. **去AI味铁律**: 严格遵守去AI味规则，禁止使用"值得注意的是""综上所述"等AI常用语。
5. **习题设计**: 按认知层次设计4类习题——选择题(记忆/理解)、填空题(理解/应用)、简答题(分析/评价)、应用题(应用/创造)。
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

## Output Specification

Report the following upon completion:
1. Chapter number and title
2. Word count
3. Identified chart requirements ([图表:...] and [插图:...] markers)
4. Exercise count and type distribution
5. Chapter file path

## Constraints

- Word count must match the outline requirement (default 5000 words)
- Anti-AI-tone language is mandatory (see anti_ai_rules.md)
- Terminology must be consistent with the terminology table
- Code examples must be runnable
- Exercises must cover all 4 types (choice, fill-in, short answer, application)
- Chart markers must use standard format: `[图表: ...]` or `[插图: ...]`

## Required Enrichment Pass

Before writing a chapter, run an enrichment pass unless the user explicitly says not to use external material.

1. Use the `multi-search-engine` skill with `web_fetch` to build a small Web Evidence Pack for the chapter topic. Do not use Bocha `web_search`.
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
