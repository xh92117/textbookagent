import os
import re
import shutil
import textwrap
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from common.log import logger
from ..sandbox.chart_generator import ChartGenerator
from ..sandbox.executor import SandboxExecutor
from ..sandbox.image_prompt import ImageGenerationRequest, ImagePromptEngineer


@dataclass
class VisualAssetDecision:
    description: str
    kind: str
    source: str
    path: str = ""
    status: str = "pending"
    reason: str = ""
    evidence: List[str] = field(default_factory=list)


class VisualAssetRouter:
    """Low-context router for textbook visual assets.

    The router deliberately uses local metadata and short descriptions instead
    of sending chapter text to an LLM. It follows this order:
    chart/code -> knowledge image asset -> web image hook -> image model -> local fallback.
    """

    CHART_TERMS = (
        "图表", "曲线", "柱状", "条形", "饼图", "雷达", "矩阵", "流程", "架构",
        "网络", "关系", "图谱", "时间线", "对比", "分布", "趋势", "链", "推演", "金字塔", "框架", "示意",
        "chart", "flow", "architecture", "network", "matrix", "timeline",
    )

    def __init__(self, book_dir: str, book_id: str = "", workspace_root: str = ""):
        self.book_dir = book_dir
        self.book_id = book_id
        self.workspace_root = workspace_root or os.path.dirname(os.path.dirname(book_dir))
        self.charts_dir = os.path.join(book_dir, "assets", "charts")
        self.images_dir = os.path.join(book_dir, "assets", "images")
        os.makedirs(self.charts_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)

    def resolve_chart(self, description: str, chapter_num: int, index: int, chart_type: str = "auto") -> VisualAssetDecision:
        filename = f"chapter{chapter_num}_chart{index}.png"
        path = self._generate_chart(description, filename, chart_type=chart_type)
        ok, reason = self._validate_asset(path, min_width=320, min_height=220)
        if ok:
            return VisualAssetDecision(description, "chart", "code_chart", path, "success", "generated from local code templates")
        return VisualAssetDecision(description, "chart", "code_chart", path or "", "failed", f"chart generation failed: {reason}")

    def resolve_image(self, description: str, chapter_num: int, index: int, image_type: str = "illustration") -> VisualAssetDecision:
        if self.is_chart_like(description):
            filename = f"chapter{chapter_num}_img{index}.png"
            path = self._generate_diagram(description, filename)
            ok, reason = self._validate_asset(path, min_width=320, min_height=220)
            if ok:
                return VisualAssetDecision(description, "diagram", "code_diagram", path, "success", "image request classified as chart-like diagram")
            logger.warning(f"Generated diagram rejected by asset gate: {reason}")

        kb = self._find_knowledge_image(description)
        if kb:
            target = self._copy_asset(kb["path"], f"chapter{chapter_num}_img{index}")
            ok, reason = self._validate_asset(target, min_width=160, min_height=120)
            if ok:
                return VisualAssetDecision(description, "image", "knowledge_base", target, "success", "matched indexed knowledge image", [kb.get("summary", "")])
            logger.warning(f"Knowledge image rejected by asset gate: {reason}")

        web = self._find_web_image(description)
        if web:
            return VisualAssetDecision(description, "image", "web", web, "success", "matched web image")

        model = self._generate_model_image(description, chapter_num, index, image_type=image_type)
        ok, reason = self._validate_asset(model.path, min_width=320, min_height=220)
        if model.status == "success" and ok:
            return model
        if model.status == "success":
            model.status = "failed"
            model.reason = f"image model output rejected by asset gate: {reason}"

        fallback = self._generate_fallback(description, f"chapter{chapter_num}_img{index}.png", reason=model.reason)
        ok, fallback_reason = self._validate_asset(fallback, min_width=320, min_height=220)
        if ok:
            return VisualAssetDecision(
                description,
                "image",
                "fallback",
                fallback,
                "success",
                "image model unavailable or invalid; inserted clearly labeled local placeholder",
                [model.reason, "placeholder=true"],
            )
        return VisualAssetDecision(description, "image", "fallback", fallback or "", "failed", f"fallback generation failed: {fallback_reason}")

    def is_chart_like(self, description: str) -> bool:
        text = (description or "").lower()
        return any(term.lower() in text for term in self.CHART_TERMS)

    def _generate_chart(self, desc: str, filename: str, chart_type: str = "auto") -> str:
        executor = SandboxExecutor(timeout=45, output_dir=self.charts_dir)
        chart_gen = ChartGenerator(executor=executor)
        try:
            if chart_type in ("bar",) or any(k in desc for k in ("柱", "条形", "对比", "排名")):
                result = chart_gen.generate_bar_chart("['方案A','方案B','方案C']", "[78, 86, 72]", title=desc, filename=filename)
            elif chart_type in ("pie",) or any(k in desc for k in ("饼", "占比", "比例")):
                result = chart_gen.generate_pie_chart("['监测','研判','调度','复盘']", "[25, 30, 30, 15]", title=desc, filename=filename)
            elif chart_type in ("scatter",) or "散点" in desc:
                result = chart_gen.generate_scatter_chart("list(range(1, 11))", "[2,3,5,7,8,11,13,16,18,21]", title=desc, filename=filename)
            elif chart_type in ("network",) or any(k in desc for k in ("网络", "关系", "图谱", "链", "推演")):
                result = chart_gen.generate_network_graph(
                    nodes_code="G.add_nodes_from(['数据源','智能体','工具','任务','结果','复盘'])",
                    edges_code="G.add_edges_from([('数据源','智能体'),('智能体','工具'),('工具','任务'),('任务','结果'),('结果','复盘'),('复盘','智能体')])",
                    title=desc,
                    filename=filename,
                )
            elif chart_type in ("radar",) or "雷达" in desc:
                result = chart_gen.execute_custom_code(self._radar_code(desc), filename=filename)
            else:
                result = chart_gen.generate_line_chart("list(range(1, 7))", "[62, 70, 79, 83, 88, 92]", title=desc, filename=filename)
            return self._pick_output(result, filename)
        except Exception as exc:
            logger.warning(f"Chart generation failed: {exc}")
            return ""

    def _generate_diagram(self, desc: str, filename: str) -> str:
        path = os.path.join(self.images_dir, filename)
        try:
            from PIL import Image, ImageDraw, ImageFont

            img = Image.new("RGB", (1400, 900), "#f8fafc")
            draw = ImageDraw.Draw(img)
            font_title = self._font(34)
            font_head = self._font(28)
            font_body = self._font(22)
            y_title = 42
            for line in textwrap.wrap(desc, width=38)[:2]:
                draw.text((70, y_title), line, fill="#0f172a", font=font_title)
                y_title += 54
            center = (500, 315, 900, 565)
            draw.rounded_rectangle(center, radius=18, fill="#ffffff", outline="#2563eb", width=4)
            draw.text((595, 355), "AI Agent", fill="#1e3a8a", font=font_head)
            labels = ["Input", "Plan", "Tools", "Review", "Output"]
            boxes = [(80, 210, 340, 340), (80, 560, 340, 690), (1060, 210, 1320, 340), (1060, 560, 1320, 690), (565, 700, 835, 830)]
            for rect, label in zip(boxes, labels):
                draw.rounded_rectangle(rect, radius=14, fill="#ffffff", outline="#94a3b8", width=3)
                draw.text((rect[0] + 30, rect[1] + 45), label, fill="#0f172a", font=font_head)
                self._arrow(draw, ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2), (700, 440))
            caption = "Code-generated diagram; labels are kept minimal to avoid unreadable AI text."
            draw.text((70, 850), caption, fill="#475569", font=font_body)
            img.save(path, "PNG")
            return path
        except Exception as exc:
            logger.warning(f"Diagram generation failed: {exc}")
            return ""

    def _find_knowledge_image(self, description: str) -> Optional[dict]:
        index_path = os.path.join(self.workspace_root, "knowledge", self.book_id, "_llm_wiki", "index.json")
        if not os.path.isfile(index_path):
            return None
        try:
            import json
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except Exception as exc:
            logger.warning(f"Failed to read knowledge image index: {exc}")
            return None
        candidates = []
        terms = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9_-]{2,}", description or ""))
        for source in index.get("sources", []):
            for asset in source.get("assets") or []:
                text = " ".join([asset.get("description", ""), asset.get("path", ""), source.get("name", "")])
                score = len(terms & set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9_-]{2,}", text)))
                if score > 0:
                    candidates.append((score, asset, source))
        if not candidates:
            return None
        _, asset, source = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        rel = asset.get("path", "")
        full = os.path.join(self.workspace_root, "knowledge", self.book_id, rel) if rel and not os.path.isabs(rel) else rel
        return {"path": full, "summary": asset.get("description", "") or source.get("name", "")}

    def _copy_asset(self, source_path: str, stem: str) -> str:
        if not source_path or not os.path.isfile(source_path):
            return ""
        ext = os.path.splitext(source_path)[1] or ".png"
        target = os.path.join(self.images_dir, stem + ext)
        try:
            shutil.copyfile(source_path, target)
            return target
        except Exception as exc:
            logger.warning(f"Failed to copy knowledge image asset: {exc}")
            return ""

    def _find_web_image(self, description: str) -> str:
        # Hook reserved for a later licensed-image search provider. Disabled by
        # default to avoid token/context cost and accidental copyright misuse.
        return ""

    def _generate_model_image(self, desc: str, chapter_num: int, index: int, image_type: str) -> VisualAssetDecision:
        filename = f"chapter{chapter_num}_img{index}.png"
        prompt_engineer = ImagePromptEngineer()
        req = ImageGenerationRequest(description=desc, image_type=image_type or "illustration", style="professional", size="landscape_4_3", language="en")
        prompt_path = os.path.join(self.images_dir, f"chapter{chapter_num}_img{index}.prompt.txt")
        try:
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(prompt_engineer.generate_prompt(req))
            result = prompt_engineer.generate_and_save(req, self.images_dir, filename)
            if result.get("status") == "success":
                return VisualAssetDecision(desc, "image", "image_model", os.path.join(self.images_dir, filename), "success", f"generated by {result.get('model', 'configured image model')}", [prompt_path])
            return VisualAssetDecision(desc, "image", "image_model", "", "failed", result.get("error", "image model failed"), [prompt_path])
        except Exception as exc:
            return VisualAssetDecision(desc, "image", "image_model", "", "failed", str(exc), [prompt_path])

    def _generate_fallback(self, desc: str, filename: str, reason: str = "") -> str:
        path = os.path.join(self.images_dir, filename)
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (1200, 820), "#f8fafc")
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle((60, 60, 1140, 760), radius=18, fill="#ffffff", outline="#94a3b8", width=3)
            draw.text((110, 115), "Textbook Illustration Placeholder", fill="#0f172a", font=self._font(44))
            y = 210
            for line in textwrap.wrap(desc or "Pending illustration", width=34)[:7]:
                draw.text((110, y), line, fill="#334155", font=self._font(30))
                y += 48
            if reason:
                draw.text((110, 700), "Generated locally after image service failure.", fill="#64748b", font=self._font(24))
            img.save(path, "PNG")
            return path
        except Exception as exc:
            logger.warning(f"Fallback image generation failed: {exc}")
            return ""

    def _pick_output(self, result, filename: str) -> str:
        if not result or not result.success or not result.output_files:
            return ""
        exact = [p for p in result.output_files if os.path.basename(p) == filename]
        return exact[0] if exact else result.output_files[0]

    def _validate_asset(self, path: str, min_width: int = 160, min_height: int = 120) -> Tuple[bool, str]:
        if not path:
            return False, "empty path"
        if path.startswith(("http://", "https://")):
            return True, "remote asset"
        if not os.path.isfile(path):
            return False, "file not found"
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            return False, f"cannot stat file: {exc}"
        if size < 1024:
            return False, f"file too small ({size} bytes)"

        ext = os.path.splitext(path)[1].lower()
        if ext == ".svg":
            try:
                text = open(path, "r", encoding="utf-8", errors="ignore").read(4096)
            except Exception as exc:
                return False, f"cannot read svg: {exc}"
            if "<svg" not in text.lower():
                return False, "not a valid svg"
            return True, "valid svg"

        try:
            from PIL import Image, ImageStat

            with Image.open(path) as img:
                width, height = img.size
                if width < min_width or height < min_height:
                    return False, f"image too small ({width}x{height})"
                sample = img.convert("RGB").resize((64, 64))
                stat = ImageStat.Stat(sample)
                if max(stat.var or [0]) < 2.0:
                    return False, "image appears blank or near-solid"
                return True, f"valid image ({width}x{height}, {size} bytes)"
        except Exception as exc:
            return False, f"cannot decode image: {exc}"

    def _radar_code(self, title: str) -> str:
        return f"""
import math
labels = ['鲁棒性', '冗余性', '资源性', '快速性', '可观测性', '适应性']
values = [0.78, 0.64, 0.72, 0.69, 0.84, 0.75]
angles = [n / float(len(labels)) * 2 * math.pi for n in range(len(labels))]
values += values[:1]
angles += angles[:1]
fig = plt.figure(figsize=(7, 7))
ax = plt.subplot(111, polar=True)
ax.plot(angles, values, color='#2563eb', linewidth=2)
ax.fill(angles, values, color='#60a5fa', alpha=0.28)
ax.set_xticks(angles[:-1])
ax.set_xticklabels(labels)
ax.set_ylim(0, 1)
ax.set_title({title!r}, pad=24)
ax.grid(True, alpha=0.35)
"""

    def _font(self, size: int):
        from PIL import ImageFont
        for name in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "msyh.ttc", "simhei.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _arrow(self, draw, start, end):
        import math
        draw.line((start, end), fill="#2563eb", width=4)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        for delta in (2.55, -2.55):
            x = end[0] - 16 * math.cos(angle + delta)
            y = end[1] - 16 * math.sin(angle + delta)
            draw.line((end[0], end[1], x, y), fill="#2563eb", width=4)
