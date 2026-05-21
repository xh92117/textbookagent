import json
import os
import re
import textwrap
import time
from typing import Any, Dict

from agent.textbook.sandbox.image_prompt import ImageGenerationRequest, ImagePromptEngineer
from agent.tools.base_tool import BaseTool, ToolResult


class TextbookImageTool(BaseTool):
    name: str = "textbook_image"
    description: str = (
        "Generate or fallback-create a textbook image asset in the canonical "
        "textbooks/<book_id>/assets/images directory. Use this instead of bash "
        "or write when the chapter needs a figure, illustration, diagram, or "
        "local placeholder after the remote image API fails."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "book_id": {
                "type": "string",
                "description": "Textbook id, for example tb_3df776e0",
            },
            "description": {
                "type": "string",
                "description": "What the image should show. Be concrete and educational.",
            },
            "chapter_num": {
                "type": "integer",
                "description": "Chapter number for naming, for example 7",
            },
            "figure_num": {
                "type": "integer",
                "description": "Figure sequence inside the chapter, for example 1",
            },
            "title": {
                "type": "string",
                "description": "Figure title, for example 图7-1 多模态模型架构示意图",
            },
            "image_type": {
                "type": "string",
                "description": "diagram, illustration, screenshot, photo, flowchart, concept_map, architecture",
            },
            "style": {
                "type": "string",
                "description": "professional, minimal, or detailed",
            },
            "size": {
                "type": "string",
                "description": "square_hd, square, portrait_4_3, portrait_16_9, landscape_4_3, landscape_16_9",
            },
            "filename": {
                "type": "string",
                "description": "Optional output filename. Extension defaults to .png.",
            },
            "generate_remote": {
                "type": "boolean",
                "description": "Whether to try the configured remote image model before local fallback.",
            },
        },
        "required": ["book_id", "description"],
    }

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        book_id = str(args.get("book_id", "")).strip()
        description = str(args.get("description", "")).strip()
        if not book_id:
            return ToolResult.fail("book_id is required")
        if not description:
            return ToolResult.fail("description is required")

        try:
            from bridge.textbook_bridge import get_bridge

            bridge = get_bridge()
            if not bridge.get_textbook(book_id):
                return ToolResult.fail(f"Textbook not found: {book_id}")
            mgr = bridge._memory_manager.get_truth_manager(book_id)
            image_dir = os.path.join(mgr.book_dir, "assets", "images")
            os.makedirs(image_dir, exist_ok=True)

            chapter_num = self._to_int(args.get("chapter_num"), 0)
            figure_num = self._to_int(args.get("figure_num"), 0)
            title = str(args.get("title", "")).strip()
            image_type = str(args.get("image_type") or "diagram").strip() or "diagram"
            style = str(args.get("style") or "professional").strip() or "professional"
            size = str(args.get("size") or "landscape_4_3").strip() or "landscape_4_3"
            filename = self._normalize_filename(args.get("filename"), chapter_num, figure_num, title)

            engineer = ImagePromptEngineer()
            request = ImageGenerationRequest(
                description=description,
                image_type=self._normalize_image_type(image_type),
                style=style if style in engineer.STYLE_KEYWORDS else "professional",
                size=size if size in engineer.SIZE_MAP else "landscape_4_3",
                language="zh",
            )

            result: Dict[str, Any]
            if args.get("generate_remote", True) is False:
                prompt = engineer.generate_prompt(request)
                result = {"status": "skipped", "prompt": prompt, "error": "remote generation skipped"}
            else:
                result = engineer.generate_and_save(request, image_dir, filename)

            source = "remote"
            if result.get("status") != "success" or not os.path.exists(os.path.join(image_dir, filename)):
                source = "local_fallback"
                prompt = result.get("prompt") or engineer.generate_prompt(request)
                fallback = self._create_placeholder(
                    os.path.join(image_dir, filename),
                    title=title or self._default_title(chapter_num, figure_num),
                    description=description,
                )
                result = {
                    "status": "success",
                    "prompt": prompt,
                    "image_path": fallback,
                    "filename": os.path.basename(fallback),
                    "source": source,
                    "remote_error": result.get("error", ""),
                }

            prompt_path = os.path.join(image_dir, os.path.splitext(filename)[0] + ".prompt.txt")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(result.get("prompt", ""))

            rel_path = f"assets/images/{os.path.basename(result.get('filename') or filename)}"
            payload = {
                "book_id": book_id,
                "chapter_num": chapter_num,
                "figure_num": figure_num,
                "title": title,
                "status": "success",
                "source": result.get("source") or source,
                "path": result.get("image_path") or os.path.join(image_dir, filename),
                "relative_path": rel_path,
                "prompt_path": prompt_path,
                "markdown": f"![{title or description}]({rel_path})",
                "remote_error": result.get("remote_error", ""),
                "message": "Textbook image asset is ready. Insert the markdown into the chapter where the figure is referenced.",
            }
            return ToolResult.success(payload)
        except Exception as exc:
            return ToolResult.fail(f"textbook_image error: {exc}")

    @staticmethod
    def _to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @classmethod
    def _normalize_filename(cls, value: Any, chapter_num: int, figure_num: int, title: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            prefix = f"fig_{chapter_num}_{figure_num}" if chapter_num and figure_num else f"img_{int(time.time())}"
            slug = cls._slug(title) if title else ""
            raw = f"{prefix}_{slug}" if slug else prefix
        raw = os.path.basename(raw.replace("\\", "/"))
        stem, ext = os.path.splitext(raw)
        ext = ext.lower() if ext else ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"
        return cls._slug(stem) + ext

    @staticmethod
    def _slug(text: str) -> str:
        text = re.sub(r"\s+", "_", text.strip())
        text = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text[:80] or "image"

    @staticmethod
    def _normalize_image_type(image_type: str) -> str:
        lowered = (image_type or "").lower()
        if lowered in ("flowchart", "concept_map", "architecture", "schematic"):
            return "diagram"
        return lowered if lowered in ("diagram", "illustration", "screenshot", "photo") else "diagram"

    @staticmethod
    def _default_title(chapter_num: int, figure_num: int) -> str:
        if chapter_num and figure_num:
            return f"图{chapter_num}-{figure_num}"
        return "教材插图"

    def _create_placeholder(self, path: str, title: str, description: str) -> str:
        try:
            from PIL import Image, ImageDraw, ImageFont

            width, height = 1280, 720
            image = Image.new("RGB", (width, height), "#f8fafc")
            draw = ImageDraw.Draw(image)
            draw.rectangle((32, 32, width - 32, height - 32), outline="#2563eb", width=4)
            draw.rectangle((64, 84, width - 64, 176), fill="#dbeafe")
            font_title = self._font(42)
            font_body = self._font(28)
            draw.text((88, 104), title[:40], fill="#1e3a8a", font=font_title)
            lines = textwrap.wrap(description, width=34)[:8]
            y = 230
            for line in lines:
                draw.text((96, y), line, fill="#0f172a", font=font_body)
                y += 48
            draw.text((96, height - 92), "Local fallback image generated by TextbookAgent", fill="#64748b", font=self._font(22))
            image.save(path)
            return path
        except Exception:
            svg_path = os.path.splitext(path)[0] + ".svg"
            safe_title = self._xml_escape(title)
            safe_desc = self._xml_escape(description[:500])
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">'
                '<rect width="1280" height="720" fill="#f8fafc"/>'
                '<rect x="32" y="32" width="1216" height="656" fill="none" stroke="#2563eb" stroke-width="4"/>'
                '<rect x="64" y="84" width="1152" height="92" fill="#dbeafe"/>'
                f'<text x="88" y="140" font-size="42" fill="#1e3a8a">{safe_title}</text>'
                f'<text x="96" y="240" font-size="28" fill="#0f172a">{safe_desc}</text>'
                '<text x="96" y="640" font-size="22" fill="#64748b">Local fallback image generated by TextbookAgent</text>'
                "</svg>"
            )
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg)
            return svg_path

    @staticmethod
    def _font(size: int):
        try:
            from PIL import ImageFont

            for candidate in (
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/simsun.ttc",
                "C:/Windows/Fonts/arial.ttf",
            ):
                if os.path.exists(candidate):
                    return ImageFont.truetype(candidate, size)
            return ImageFont.load_default()
        except Exception:
            return None

    @staticmethod
    def _xml_escape(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
