from .base import TextbookBaseAgent
from ..prompts.writer_prompts import WRITER_SYSTEM_PROMPT, WRITER_USER_PROMPT_TEMPLATE

import re


_CHART_MARKER_RE = re.compile(r'\[(?:图表|图|Chart|chart)\s*[:：]\s*([^\]]+?)\]')
_IMAGE_MARKER_RE = re.compile(r'\[(?:插图|图片|Image|image|Illustration|illustration)\s*[:：]\s*([^\]]+?)\]')


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

        return {
            'content': content,
            'chapter_number': input_data.get('chapter_number', 0),
            'chapter_title': input_data.get('chapter_title', ''),
            'chart_requirements': chart_reqs,
            'image_requirements': img_reqs,
            'word_count': len(content),
        }
