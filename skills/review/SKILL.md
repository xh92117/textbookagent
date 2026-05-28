---
name: textbook-review
description: Use when the user requests outline quality review, chapter content review, or overall textbook quality assessment. 8 dimensions for outlines, 22 dimensions for chapters.
triggers:
  - 审查大纲
  - 审查章节
  - 评估质量
  - 检查质量
  - 教材审查
allowed-tools:
  - textbook_chapter
  - textbook_outline
  - read
  - knowledge_query
  - memory_search
  - memory_get
---

# Textbook Quality Review

## Current Tool Contract

- Use `textbook_outline` to read outline and terminology artifacts.
- Use `textbook_chapter` to read or validate chapter artifacts.
- Use `read` only for review checklist templates or adjacent context.
- Do not modify reviewed content in this skill. Do not use `write`, `edit`, or `bash`.
- If the user asks to apply review suggestions, switch to the chapter or outline skill after reporting the review result.

Perform multi-dimensional quality review on textbook outlines or chapter content, generating structured review reports with issues classified as critical/warning/info.

## 核心指令

1. **确定审查模式**: 根据用户请求判断审查对象——大纲审查(8维度)或章节审查(22维度)。
2. **读取审查对象**: 使用 `read` 读取大纲或章节文件。
3. **参考审查清单**: 读取对应审查清单模板作为维度参考。
4. **逐维度审查**:
   - **大纲8维度**: 知识完整性、逻辑递进性、认知层次分布、课标符合度、篇幅均衡性、前置依赖正确性、术语一致性、实践环节覆盖
   - **章节22维度**: 知识准确性、逻辑连贯性、术语一致性、难度梯度、认知层次匹配、概念定义规范、公式/定理正确、代码示例正确、图表合理性、习题质量、章节结构完整、段落划分合理、标题层级清晰、语言规范性、表述清晰性、去AI味、教学目标明确、教学方法适配、学习支持充分、评估方式合理、篇幅适中、前后章节衔接
5. **问题分级**: critical(必须修改) / warning(建议修改) / info(可选优化)
6. **生成审查报告**: 输出JSON格式审查结果，包含各维度评分和问题列表。

## 工作流示例

### 示例1：审查大纲
- **用户输入**: "帮我审查一下大纲质量"
- **模型思考**: 用户要求审查大纲，使用8维度审查模式。
- **模型行动**:
  1. `read("outline.md")` 读取大纲
  2. `read("<base_dir>/templates/review_checklist_outline.md")` 读取审查清单
  3. 逐维度评估，记录问题
  4. 生成审查报告，按三级分类
  5. 向用户汇报审查结果

### 示例2：审查单章节
- **用户输入**: "审查第3章的内容质量"
- **模型思考**: 章节审查模式，22维度。
- **模型行动**:
  1. `read("chapters/chapter_003.md")` 读取章节
  2. `read("<base_dir>/templates/review_checklist_chapter.md")` 读取审查清单
  3. 22维度逐项审查
  4. 生成审查报告

## Tool Usage Specification

- `read`: Read outline/chapter files and review checklist templates
  - Syntax: `read("<file_path>")`
  - Outline checklist: `read("<base_dir>/templates/review_checklist_outline.md")`
  - Chapter checklist: `read("<base_dir>/templates/review_checklist_chapter.md")`
- Review reports should be returned to the user unless a visible canonical review/status tool is provided by the current route.

## Output Specification

Review report must include:
1. Review mode (outline/chapter) and target object
2. Per-dimension score (0-10) and issue list
3. Critical / Warning / Info issue counts
4. Overall score and pass/fail verdict
5. Revision suggestions summary

## Constraints

- All dimensions must be reviewed — skipping is prohibited
- Issue severity must be strict: correctness impact = critical, quality impact = warning, optional improvement = info
- Vague evaluations are prohibited — every issue must include specific location and revision suggestion
- Review report must use JSON format
- Pipeline review uses the dedicated system setting `review_model` / `review_bot_type`; do not assume it is the same model used for chapter writing.
- When reviewing generated chapters, verify whether `[图表:...]` and `[插图:...]` markers were replaced by real Markdown media links, and flag missing media as a quality issue.
