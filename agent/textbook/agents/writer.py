from .base import TextbookBaseAgent
from ..prompts.writer_prompts import WRITER_SYSTEM_PROMPT, WRITER_USER_PROMPT_TEMPLATE
from ..metrics import measure_content

import json
import re


_CHART_MARKER_RE = re.compile(r'\[(?:图表|图|Chart|chart)\s*[:：]\s*([^\]]+?)\]')
_IMAGE_MARKER_RE = re.compile(r'\[(?:插图|图片|Image|image|Illustration|illustration)\s*[:：]\s*([^\]]+?)\]')
_VISUAL_JSON_RE = re.compile(
    r'###\s*VISUAL_ASSETS\s*```(?:json)?\s*([\s\S]*?)```',
    re.IGNORECASE,
)


class WriterAgent(TextbookBaseAgent):
    def get_system_prompt(self) -> str:
        return WRITER_SYSTEM_PROMPT

    def get_agent_type(self) -> str:
        return "writer"

    def _build_user_prompt(self, input_data: dict, context: dict = None) -> str:
        return WRITER_USER_PROMPT_TEMPLATE.format(
            chapter_number=input_data.get('chapter_number', 0),
            chapter_title=input_data.get('chapter_title', ''),
            objective=input_data.get('objective', ''),
            key_results=input_data.get('key_results', ''),
            cognitive_level=input_data.get('cognitive_level', ''),
            prerequisites=input_data.get('prerequisites', ''),
            key_concepts=input_data.get('key_concepts', ''),
            target_words=input_data.get('target_words', 5000),
            context=input_data.get('context', ''),
            terminology=input_data.get('terminology', ''),
            writing_spec=input_data.get('writing_spec', ''),
        )

    def _parse_output(self, llm_output: str, input_data: dict) -> dict:
        content = llm_output
        if '### CHAPTER_CONTENT' in llm_output:
            parts = llm_output.split('### CHAPTER_CONTENT')
            content = parts[-1].strip() if len(parts) > 1 else llm_output

        chart_reqs = []
        img_reqs = []
        seen_charts = set()
        seen_images = set()

        for asset in self._parse_visual_assets(llm_output):
            asset_type = str(asset.get("type", "")).lower()
            desc = str(asset.get("description", "")).strip()
            if not desc:
                continue
            if asset_type in ("chart", "diagram", "graph", "table_visual"):
                if desc not in seen_charts:
                    chart_reqs.append({
                        'description': desc,
                        'chart_type': asset.get('chart_type', 'auto') or 'auto',
                        'insert_after': asset.get('insert_after', ''),
                    })
                    seen_charts.add(desc)
            elif asset_type in ("image", "illustration", "photo", "screenshot"):
                if desc not in seen_images:
                    img_reqs.append({
                        'description': desc,
                        'image_type': asset.get('image_type', 'illustration') or 'illustration',
                        'insert_after': asset.get('insert_after', ''),
                    })
                    seen_images.add(desc)

        for match in _CHART_MARKER_RE.finditer(content):
            desc = match.group(1).strip()
            if desc and desc not in seen_charts:
                chart_reqs.append({'description': desc, 'chart_type': 'auto'})
                seen_charts.add(desc)
        for match in _IMAGE_MARKER_RE.finditer(content):
            desc = match.group(1).strip()
            if desc and desc not in seen_images:
                img_reqs.append({'description': desc, 'image_type': 'illustration'})
                seen_images.add(desc)

        metrics = measure_content(content)
        return {
            'content': content,
            'chapter_number': input_data.get('chapter_number', 0),
            'chapter_title': input_data.get('chapter_title', ''),
            'chart_requirements': chart_reqs,
            'image_requirements': img_reqs,
            'word_count': metrics.effective_word_count,
            'metrics': metrics.to_dict(),
        }

    def _parse_visual_assets(self, llm_output: str) -> list:
        match = _VISUAL_JSON_RE.search(llm_output or "")
        if not match:
            return []
        try:
            payload = json.loads(match.group(1).strip())
        except Exception:
            return []
        if isinstance(payload, dict):
            assets = payload.get("visual_assets", [])
        elif isinstance(payload, list):
            assets = payload
        else:
            assets = []
        return [item for item in assets if isinstance(item, dict)]
