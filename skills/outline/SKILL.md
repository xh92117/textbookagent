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
  - textbook_outline
  - read
  - knowledge_query
  - memory_search
  - memory_get
---

# Textbook Outline Generation

## Current Tool Contract

- Use `textbook_outline` for outline and terminology read/write operations.
- Use `knowledge_query`, `memory_search`, and `memory_get` for existing evidence and continuity when needed.
- Do not use `write`, `edit`, or `bash` for outline or terminology files in this skill.
- If external search tools are not selected and visible in the current turn, do not try hidden web tools.

Generate structured textbook outlines using OKR recursive decomposition, from book-level objectives down to section-level key points, with Bloom's cognitive level annotations.

## 核心指令

1. **需求分析**: 从用户输入中提取教材主题、目标读者、难度等级、课标依据、总章数等关键信息，并生成或更新教材级 WritingSpec。信息不足时主动追问。
2. **课标搜索**: 优先使用本地知识；仅当 `multi-search-engine` skill 被本轮选中且搜索工具可见时，才检索相关课程标准或教学大纲。
3. **OKR递归分解**:
   - 教材级目标(O) → 关键结果(KR)
   - 篇级目标(O) → 关键结果(KR)
   - 章级目标(O) → 关键结果(KR)
   - 节级要点
4. **认知层次标注**: 为每个节标注布鲁姆认知层次（记忆/理解/应用/分析/评价/创造），确保分布合理。
5. **前置依赖梳理**: 明确章节间的前置知识依赖关系，避免循环依赖。
6. **术语表初始化**: 提取核心术语，建立统一术语表。
7. **保存大纲**: 将大纲写入教材工作空间。
8. **规格约束**: 大纲必须服从 WritingSpec 的学习取向、内容比例、章节结构、视觉策略和字数口径。

状态管理：大纲编制过程中维护 `outline.md` 和 `terminology.md` 两个真相文件。

## 工作流示例

### 示例1：编制新大纲
- **用户输入**: "帮我编制一本《数据结构与算法》教材大纲，面向计算机专业大二学生，共12章"
- **模型思考**: 需要提取学科=数据结构与算法、受众=计算机大二、章数=12。搜索ACM/IEEE课标。
- **模型行动**:
  1. 使用本地知识或本轮已选中的搜索 skill 整理课标证据包
  2. 读取 `<base_dir>/templates/outline_template.md` 和 `<base_dir>/templates/okr_decomposition.md` 作为参考
  3. 按OKR递归分解生成大纲
  4. `textbook_outline({"action":"write_outline","content":outline_content})` 保存大纲
  5. `textbook_outline({"action":"write_terminology","content":terms})` 保存术语表

### 示例2：调整现有大纲
- **用户输入**: "大纲第5章和第6章内容太少了，合并一下，然后在后面加一章图论"
- **模型思考**: 需要读取现有大纲，找到第5、6章，合并后重新编号，新增图论章。
- **模型行动**:
  1. `read("outline.md")` 读取现有大纲
  2. 合并第5、6章，重新编号后续章节
  3. 新增图论章节
  4. 更新前置依赖关系
  5. `textbook_outline({"action":"write_outline","content":updated_outline})` 保存更新

## Tool Usage Specification

- `read`: Read existing outline files, terminology, and templates
  - Syntax: `read("<file_path>")`
  - Outline template: `read("<base_dir>/templates/outline_template.md")`
  - OKR template: `read("<base_dir>/templates/okr_decomposition.md")`
- `textbook_outline`: Read and write outline and terminology files through canonical truth files.
- External search: use the `multi-search-engine` skill only when it is selected and its tools are visible in the current turn. Do not call hidden search/fetch tools from this outline skill.

## Output Specification

Report the following upon completion:
1. Outline overview: total parts, chapters, and sections count
2. Bloom's cognitive level distribution table (percentage per level)
3. Key prerequisite dependencies between chapters
4. Terminology entry count
5. Outline file save path

## Constraints

- Outline hierarchy must not exceed 4 levels (Part → Chapter → Section → Key Point)
- Each chapter should contain 3-8 sections, unless WritingSpec.chapter_structure requires a different stable teaching layout
- Cognitive level distribution must satisfy: Remember ≤ 20%, Understand+Apply ≥ 40%, Analyze+Evaluate ≥ 25%, Create ≥ 5%
- Circular dependencies between chapters are prohibited
- Terminology must be consistent throughout — no synonym duplication
- Outline must state how chapters reflect WritingSpec, so writer/reviewer agents can inherit the same contract

## Required Search Pass

Before finalizing an outline, use local knowledge first. Use the `multi-search-engine` skill for curriculum standards, comparable course syllabi, textbook tables of contents, and authoritative reference structures only when that skill is selected and its tools are visible. Keep the evidence compact:

- Source title and URL
- Useful structural insight
- How it changes the outline

Do not paste raw search results or full pages into the outline prompt. Summarize them first.
