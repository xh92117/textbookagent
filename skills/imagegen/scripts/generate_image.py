import sys
import json
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from agent.textbook.sandbox.image_prompt import ImagePromptEngineer, ImageGenerationRequest
from agent.tools.textbook_image.textbook_image import TextbookImageTool


def _infer_book_id(output_dir: str) -> str:
    parts = os.path.normpath(output_dir or "").split(os.sep)
    for part in parts:
        if part.startswith("tb_"):
            return part
    return ""


def _prompt_note(title: str, description: str, prompt: str, error: str = "") -> str:
    lines = [
        f"> **插图生成备注：{title or '待生成插图'}**",
        "> 当前环境未能生成图片资产，后续可根据下方提示词重新生成并替换本备注。",
        f"> 插图需求：{description}",
        f"> 生成提示词：{prompt}",
    ]
    if error:
        lines.append(f"> 失败原因：{error}")
    return "\n".join(lines)

def main():
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({
            "status": "error",
            "error": f"invalid json arguments: {exc}",
            "hint": "Pass a single JSON object argument. Prefer the textbook_image tool instead of this compatibility script.",
        }, ensure_ascii=False))
        return
    description = args.get("description", "")
    image_type = args.get("image_type", "illustration")
    style = args.get("style", "professional")
    subject = args.get("subject", "")
    output_dir = args.get("output_dir", ".")
    image_size = args.get("image_size", "landscape_4_3")
    generate = args.get("generate", True)
    book_id = args.get("book_id") or _infer_book_id(output_dir)
    chapter_num = args.get("chapter_num", 0)
    figure_num = args.get("figure_num", 0)
    title = args.get("title", "")
    filename = args.get("filename", "")

    engineer = ImagePromptEngineer()

    request = ImageGenerationRequest(
        description=description,
        image_type=image_type,
        style=style,
        size=image_size,
        subject=subject
    )

    prompt = engineer.generate_prompt(request)
    if not book_id:
        print(json.dumps({
            "status": "prompt_only",
            "prompt": prompt,
            "prompt_note_markdown": _prompt_note(title, description, prompt, "book_id is required for textbook_image"),
            "error": "book_id is required. This compatibility script no longer writes prompt files.",
        }, ensure_ascii=False))
        return

    tool_args = {
        "book_id": book_id,
        "description": description,
        "chapter_num": chapter_num,
        "figure_num": figure_num,
        "title": title,
        "image_type": image_type,
        "style": style,
        "size": image_size,
        "generate_remote": bool(generate),
    }
    if filename:
        tool_args["filename"] = filename

    result = TextbookImageTool().execute(tool_args)
    payload = result.result if isinstance(result.result, dict) else {"message": str(result.result)}
    payload.setdefault("status", result.status)
    if result.status != "success":
        payload["status"] = "prompt_only"
        payload["prompt"] = prompt
        payload["prompt_note_markdown"] = _prompt_note(title, description, prompt, str(result.result))
        payload["error"] = str(result.result)
    print(json.dumps(payload, ensure_ascii=False))

if __name__ == "__main__":
    main()
