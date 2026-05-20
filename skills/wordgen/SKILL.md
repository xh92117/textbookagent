---
name: textbook-wordgen
description: Use when the user requests Word document generation, textbook export, or document download. Supports 3 style templates and selective chapter export.
triggers:
  - 生成Word
  - 导出Word
  - 下载教材
  - 导出文档
  - 生成文档
allowed-tools:
  - read
  - write
  - bash
---

# Word Document Generation

Convert textbook chapter Markdown content into formatted Word documents (.docx), supporting 3 style templates, East Asian font settings, and selective chapter export.

## 核心指令

1. **确认导出参数**: 确定格式模板(academic/modern/training)、导出章节范围、文件名。
2. **读取内容**: 读取大纲和指定章节的Markdown文件。
3. **执行转换**: 调用Word生成脚本，将Markdown转换为.docx。
4. **提供下载**: 告知用户文档路径。

## 工作流示例

### 示例1：导出整本教材
- **用户输入**: "生成Word文档"
- **模型思考**: 默认使用academic模板，导出全部章节。
- **模型行动**:
  1. 执行 `python <base_dir>/scripts/generate_word.py '{"book_id":"xxx","template":"academic","output_dir":"./output"}'`
  2. 告知用户文档路径

### 示例2：指定模板和章节
- **用户输入**: "用现代简约模板导出第1-5章"
- **模型行动**:
  1. 执行 `python <base_dir>/scripts/generate_word.py '{"book_id":"xxx","template":"modern","chapters":[1,2,3,4,5],"output_dir":"./output"}'`

## Tool Usage Specification

- `bash`: Execute Word generation script
  - Syntax: `python <base_dir>/scripts/generate_word.py '<json_args>'`
  - Parameters: `{"book_id":"...", "template":"academic|modern|training", "chapters":[1,2,3], "title":"...", "filename":"output.docx", "output_dir":"./output", "book_dir":"..."}`
- `read`: Read style template descriptions
  - Academic: `read("<base_dir>/templates/style_academic.md")`
  - Modern: `read("<base_dir>/templates/style_modern.md")`
  - Training: `read("<base_dir>/templates/style_training.md")`

## Output Specification

Report the following upon completion:
1. Document file path
2. Style template used
3. Number and list of exported chapters
4. File size

## Constraints

- Only .docx format output is supported
- Template name must be one of: academic, modern, training
- Chapter numbers must be positive integers
- Filename must not contain special characters
