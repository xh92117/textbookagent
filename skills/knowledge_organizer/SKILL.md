---
name: textbook-knowledge-organizer
description: 知识库整理技能，对教材知识库进行梳理、建立知识关联
triggers:
  - 整理知识库
  - 知识库整理
  - 梳理知识
  - organize knowledge
allowed-tools:
  - read
  - write
  - ls
  - bash
---

# Textbook Knowledge Organizer

对教材知识库进行AI整理，提取知识条目、建立知识关联图谱。

## 核心指令

1. **扫描知识库**: 读取指定教材的知识库文件夹中所有文档
2. **提取知识条目**: 使用AI从文档中提取结构化知识条目（标题、摘要、关键词、关联概念）
3. **建立关联图谱**: 解析知识条目间的关键词和关联概念，构建节点和边的图谱
4. **生成交叉引用**: 在知识条目间自动建立交叉引用链接

## 工作流示例

### 示例1：整理知识库
- **用户输入**: "整理知识库" 或 "整理教材xxx的知识库"
- **模型行动**:
  1. 识别目标教材book_id
  2. `bash("python <base_dir>/scripts/organize.py '{\"book_id\":\"xxx\",\"action\":\"organize\"}'")`
  3. 报告整理结果

### 示例2：查看知识图谱
- **用户输入**: "查看知识关联图谱"
- **模型行动**:
  1. `bash("python <base_dir>/scripts/organize.py '{\"book_id\":\"xxx\",\"action\":\"graph\"}'")`
  2. 展示图谱数据摘要

## Tool Usage Specification

- `bash`: Execute organize script
  - Syntax: `python <base_dir>/scripts/organize.py '<json_args>'`
  - Parameters: `{"book_id":"...", "action":"organize|graph"}`
- `read`: Read knowledge files
- `write`: Write organized knowledge entries
- `ls`: List knowledge directory contents

## Output Specification

Report the following upon completion:
1. Organized entry count
2. Cross-reference count
3. Knowledge graph node and edge count
4. Category distribution summary

## LLM-WIKI Structure

The knowledge base now uses an LLM-WIKI layout:

```text
knowledge/_llm_wiki/
  index.json
  graph.json
  chunks/<chunk_id>.md
  pages/<page_slug>.md
```

`index.json` is the routing file. It contains:

- `sources`: uploaded source files
- `chunks`: raw evidence chunks with `summary`, `use_when`, `keywords`, and `content_type`
- `pages`: synthesized wiki pages
- `entities` and `relations`: graph data

When another agent needs knowledge, do not read every uploaded file. First inspect `index.json`, choose chunks whose `use_when` and `keywords` match the task, then read only those chunk/page files. This keeps context small and makes retrieval behave like Agent Skill metadata.
