---
name: textbook-fullbook
description: Use when the user requests writing an entire textbook, one-click full textbook generation, or end-to-end book creation from requirements. 7-phase pipeline orchestration.
triggers:
  - 编写教材
  - 写一本教材
  - 全教材
  - 一键生成
  - 整本教材
  - 生成教材
  - 制作教材
allowed-tools:
  - start_pipeline
  - read
  - write
  - web_fetch
---

# Full Textbook Generation

One-click end-to-end textbook creation through a 7-phase pipeline: outline → outline review → context assembly → chapter writing → chapter review → revision & polish → Word document generation. Supports pause/resume/cancel.

## 核心指令

1. **需求确认**: 从用户输入提取教材完整信息（标题、学科、受众、等级、章数等），整理成参数表格展示给用户确认。如果用户未提供某些参数，根据教材标题和学科合理推断默认值，但**必须先展示参数表格让用户确认后再启动管线**。
2. **管线启动**: 用户确认参数后，使用 `start_pipeline` 工具启动7阶段管线。管线在后台自动执行，无需手动运行脚本。
3. **进度汇报**: 管线启动后告知用户管线已启动，右侧面板可查看实时进度。
4. **最终输出**: 管线完成后生成Word文档 + 完整状态快照。

管线状态：planning → outlining → reviewing_outline → composing → writing → reviewing_chapters → revising → persisting → completed

## 工作流示例

### 示例1：用户提供了完整信息
- **用户输入**: "帮我写一本《Python程序设计》教材，面向大一新生，10章"
- **模型行动**:
  1. 提取参数并展示确认表格：

  | 参数 | 值 |
  |------|-----|
  | 教材名称 | Python程序设计 |
  | 学科 | 计算机科学 |
  | 目标读者 | 大一新生 |
  | 难度等级 | 入门 |
  | 章节数 | 10 |
  | 每章字数 | 5000 |
  | 写作风格 | 学术+实务 |

  2. 等待用户确认后，调用 `start_pipeline` 工具
  3. 告知用户管线已启动，可在右侧面板查看进度

### 示例2：需求不完整时
- **用户输入**: "生成一本土木工程智能体开发设计实务教材"
- **模型行动**:
  1. 从标题推断默认值，展示参数确认表格：

  | 参数 | 值 | 来源 |
  |------|-----|------|
  | 教材名称 | 土木工程智能体开发设计实务 | 用户提供 |
  | 学科 | 土木工程×AI交叉 | 从标题推断 |
  | 目标读者 | 本科生/研究生/从业者 | 默认 |
  | 难度等级 | 中高级 | 从学科推断 |
  | 章节数 | 10 | 默认 |
  | 每章字数 | 5000 | 默认 |
  | 写作风格 | 学术+实务 | 默认 |

  2. 告知用户："以上是我根据您的需求拟定的教材参数，如需调整请告知，确认后我将启动生成管线。"
  3. 用户确认后调用 `start_pipeline` 工具启动管线

## Tool Usage Specification

- `start_pipeline`: 启动教材生成管线（必须使用此工具，不要使用bash运行脚本）
  - 必填参数: `title` (教材标题)
  - 可选参数: `subject`, `target_audience`, `level`, `total_chapters`, `chapter_word_count`, `style`
  - 示例: `start_pipeline({"title":"Python程序设计","subject":"计算机","target_audience":"大一新生","level":"入门","total_chapters":10})`
- `read`: 读取已生成的教材大纲和章节内容
- `write`: 保存或更新教材相关文件

## 重要约束

- **必须先展示参数确认表格，等用户确认后再启动管线**，不要跳过确认步骤直接启动
- **必须使用 `start_pipeline` 工具启动管线**，绝对不要使用bash执行Python脚本或手动编写文件
- 管线启动后自动在后台运行7个阶段，无需手动干预
- 管线运行期间用户可随时暂停/恢复/取消
- 回答中不要使用emoji表情符号，使用纯文本描述

## Enrichment Requirements

The pipeline must produce rich textbook chapters, not only dry generated prose.

Before starting or while composing chapters:

1. Use `multi-search-engine` with `web_fetch` for curriculum/reference search. Do not use Bocha `web_search`.
2. Use the LLM-WIKI knowledge routing structure (`knowledge/_llm_wiki/index.json`) to select relevant chunks by `summary`, `use_when`, and `keywords`.
3. Ensure each chapter context package includes:
   - local outline and previous chapter summary
   - selected LLM-WIKI chunks/pages
   - a compact Web Evidence Pack
   - chart opportunities for sandbox generation
   - illustration opportunities for imagegen generation
4. Chapters should contain `[图表: ...]` and `[插图: ...]` markers when visuals would improve explanation. The backend pipeline will convert those markers into generated assets when possible.
