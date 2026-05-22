---
name: textbook-imagegen
description: Use when the user requests illustration generation, diagram creation, or when [插图:...] markers in chapters require generated image assets.
triggers:
  - 生成插图
  - 生成示意图
  - 画一张图
  - AI插图
  - 插图生成
allowed-tools:
  - textbook_image
  - textbook_chapter
  - read
---

# Textbook Image Generation

Use the project-native `textbook_image` tool as the primary and mandatory route for textbook illustrations. Do not use `bash` or `skills/imagegen/scripts/generate_image.py` unless the user explicitly asks for legacy script compatibility.

## Required Workflow

1. Identify the target `book_id`, `chapter_num`, figure number, title, and the exact `[插图: ...]` or figure description.
2. Call `textbook_image` directly:
   - `book_id`: canonical textbook id, for example `tb_3df776e0`
   - `chapter_num`: chapter number
   - `figure_num`: sequence number inside the chapter
   - `title`: visible figure title, for example `图7-1 多模态模型三段式架构示意图`
   - `description`: concrete educational image description
   - `image_type`: `diagram`, `illustration`, `screenshot`, `photo`, `flowchart`, `concept_map`, or `architecture`
   - `size`: usually `landscape_4_3`
3. If `textbook_image` returns `markdown`, insert that Markdown into the chapter with `textbook_chapter(action=replace_section|append_section)` at the correct location.
4. If `textbook_image` returns `status=prompt_only`, do not write any `.prompt.txt` file. Insert `prompt_note_markdown` into the chapter as a visible note at the figure location.
5. After inserting all figures or prompt notes, read the chapter once and verify no `[插图: ...]` markers remain unresolved.

## Strict Rules

- `textbook_image` is the preferred tool and should be used before any script, shell command, or manual file write.
- Do not hand-build Windows shell commands for image generation.
- Do not create standalone prompt files as the final fallback.
- If the remote image API fails, `textbook_image` will create a local textbook-style fallback image when possible.
- Only when both remote generation and local fallback creation fail may the prompt remain, and it must be inserted into the chapter body as `prompt_note_markdown`.
- Never use `textbook_chapter(action=write_chapter, content=placeholder)` to mark progress. Use `mark_completed` only after chapter content is intact.

## Output To User

Report:

1. Which figures were processed.
2. For each figure, whether the source is remote image, local fallback image, or prompt note.
3. The inserted Markdown path or the fact that a visible prompt note was inserted.
