---
name: textbook-imagegen
description: Use when the user requests illustration generation, diagram creation, or when [插图:...] markers in chapters require AI-generated images.
triggers:
  - 生成插图
  - 生成示意图
  - 画一张图
  - AI插图
  - 插图生成
allowed-tools:
  - textbook_image
  - bash
  - read
  - write
---

# Image Generation

Convert textbook illustration requirements into AI image generation prompts and generate images via multimodal models. Automatically adds textbook style constraints (professional, clear, print-suitable, CMYK-friendly).

## 核心指令

1. **分析插图需求**: 从[插图:...]标记或用户描述中提取插图类型和内容。
2. **生成提示词**: 按SDXL最佳实践构建提示词，自动添加教材风格约束。
3. **生成图片**: 调用图片生成脚本，通过API生成图片。
4. **插入文档**: 将图片路径记录到章节中，供Word生成时插入。

## 工作流示例

### 示例1：从标记生成插图
- **用户输入**: 章节中有 `[插图: 计算机网络OSI七层模型示意图]`
- **模型思考**: 需要生成OSI模型示意图，类型=示意图，风格=学术。
- **模型行动**:
  1. 执行 `python <base_dir>/scripts/generate_image.py '{"description":"计算机网络OSI七层模型示意图","image_type":"concept_map","style":"academic","subject":"计算机科学","generate":true}'`
  2. 获取图片URL/路径
  3. 更新章节中的标记为实际图片路径

### 示例2：手动指定需求
- **用户输入**: "帮我生成一张数据库ER图的插图"
- **模型行动**:
  1. 构建提示词，添加教材风格约束
  2. 执行生成脚本
  3. 返回图片路径

## Tool Usage Specification

- `textbook_image`: Preferred tool. Generate the image asset directly under
  `textbooks/<book_id>/assets/images`, save a `.prompt.txt` beside it, and
  create a local fallback image if the remote API returns an error or pending
  placeholder. Do not hand-build complex Windows shell commands for image
  generation when this tool is available.

- `bash`: Execute image generation script
  - Syntax: `python <base_dir>/scripts/generate_image.py '<json_args>'`
  - Parameters: `{"description":"...", "image_type":"illustration|concept_map|equipment|scene|flowchart", "style":"academic", "subject":"...", "generate":true, "image_size":"landscape_4_3"}`
  - image_size options: square_hd, square, portrait_4_3, portrait_16_9, landscape_4_3, landscape_16_9
- `read`: Read prompt templates
  - Illustration template: `read("<base_dir>/templates/prompt_template_illustration.md")`
  - Academic style template: `read("<base_dir>/templates/prompt_template_academic.md")`

## Output Specification

Report the following upon completion:
1. Illustration description and type
2. Generated prompt text
3. Image URL or file path
4. Image dimensions

## Constraints

- Prompts must include textbook style constraints (professional, clear, print-suitable)
- Negative prompts are mandatory (blurry, low quality, watermark, etc.)
- Image size must be selected from predefined options
- Generating inappropriate content for educational scenarios is prohibited
- CMYK-friendly color palette required — avoid neon/fluorescent colors
- Save the generated prompt beside the image as `*.prompt.txt` so the user can regenerate or refine it later.
- If the remote image API fails, create a local textbook-style placeholder image and keep the Markdown image link in the chapter; never leave `[插图:...]` unresolved.
