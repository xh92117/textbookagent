---
name: textbook-outline
description: Use when the user requests textbook outline creation, structure planning, or outline adjustment. Supports OKR recursive decomposition and Bloom's taxonomy.
triggers:
  - 编制大纲
  - 生成大纲
  - 规划大纲
  - 教材结构
  - 调整大纲
allowed-tools:
  - read
  - write
  - bash
  - web_fetch
---

# Textbook Outline Generation

Generate structured textbook outlines using OKR recursive decomposition, from book-level objectives down to section-level key points, with Bloom's cognitive level annotations.

## 核心指令

1. **需求分析**: 从用户输入中提取教材主题、目标读者、难度等级、课标依据、总章数等关键信息。信息不足时主动追问。
2. **课标搜索**: 使用 `multi-search-engine` skill，通过 `web_fetch` 搜索相关课程标准或教学大纲，确保大纲符合课标要求。
3. **OKR递归分解**:
   - 教材级目标(O) → 关键结果(KR)
   - 篇级目标(O) → 关键结果(KR)
   - 章级目标(O) → 关键结果(KR)
   - 节级要点
4. **认知层次标注**: 为每个节标注布鲁姆认知层次（记忆/理解/应用/分析/评价/创造），确保分布合理。
5. **前置依赖梳理**: 明确章节间的前置知识依赖关系，避免循环依赖。
6. **术语表初始化**: 提取核心术语，建立统一术语表。
7. **保存大纲**: 将大纲写入教材工作空间。

状态管理：大纲编制过程中维护 `outline.md` 和 `terminology.md` 两个真相文件。

## 工作流示例

### 示例1：编制新大纲
- **用户输入**: "帮我编制一本《数据结构与算法》教材大纲，面向计算机专业大二学生，共12章"
- **模型思考**: 需要提取学科=数据结构与算法、受众=计算机大二、章数=12。搜索ACM/IEEE课标。
- **模型行动**:
  1. `web_fetch({"url":"https://www.bing.com/search?q=数据结构%20课程标准%20ACM%20IEEE"})` 搜索课标
  2. 读取 `<base_dir>/templates/outline_template.md` 和 `<base_dir>/templates/okr_decomposition.md` 作为参考
  3. 按OKR递归分解生成大纲
  4. `write("outline.md", outline_content)` 保存大纲
  5. `write("terminology.md", terms)` 保存术语表

### 示例2：调整现有大纲
- **用户输入**: "大纲第5章和第6章内容太少了，合并一下，然后在后面加一章图论"
- **模型思考**: 需要读取现有大纲，找到第5、6章，合并后重新编号，新增图论章。
- **模型行动**:
  1. `read("outline.md")` 读取现有大纲
  2. 合并第5、6章，重新编号后续章节
  3. 新增图论章节
  4. 更新前置依赖关系
  5. `write("outline.md", updated_outline)` 保存更新

## Tool Usage Specification

- `read`: Read existing outline files, terminology, and templates
  - Syntax: `read("<file_path>")`
  - Outline template: `read("<base_dir>/templates/outline_template.md")`
  - OKR template: `read("<base_dir>/templates/okr_decomposition.md")`
- `write`: Write outline and terminology files
  - Syntax: `write("<file_path>", "<content>")`
- `web_fetch`: Search curriculum standards and reference materials through the `multi-search-engine` skill. Do not use Bocha `web_search`.
  - Syntax: `web_fetch({"url":"https://www.bing.com/search?q=<url-encoded-query>"})`
- `bash`: Execute outline generation script (optional)
  - Syntax: `python <base_dir>/scripts/generate_outline.py '<json_args>'`
  - Parameters: `{"title":"...", "subject":"...", "target_audience":"...", "level":"...", "total_chapters":10}`

## Output Specification

Report the following upon completion:
1. Outline overview: total parts, chapters, and sections count
2. Bloom's cognitive level distribution table (percentage per level)
3. Key prerequisite dependencies between chapters
4. Terminology entry count
5. Outline file save path

## Constraints

- Outline hierarchy must not exceed 4 levels (Part → Chapter → Section → Key Point)
- Each chapter should contain 3-8 sections
- Cognitive level distribution must satisfy: Remember ≤ 20%, Understand+Apply ≥ 40%, Analyze+Evaluate ≥ 25%, Create ≥ 5%
- Circular dependencies between chapters are prohibited
- Terminology must be consistent throughout — no synonym duplication

## Required Search Pass

Before finalizing an outline, use the `multi-search-engine` skill with `web_fetch` to gather curriculum standards, comparable course syllabi, textbook tables of contents, and authoritative reference structures. Keep the evidence compact:

- Source title and URL
- Useful structural insight
- How it changes the outline

Do not paste raw search results or full pages into the outline prompt. Summarize them first.
