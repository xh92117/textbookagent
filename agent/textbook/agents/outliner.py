from .base import TextbookBaseAgent
from ..prompts.outliner_prompts import OUTLINER_SYSTEM_PROMPT, OUTLINER_USER_PROMPT_TEMPLATE


class OutlinerAgent(TextbookBaseAgent):
    def get_system_prompt(self) -> str:
        return OUTLINER_SYSTEM_PROMPT

    def get_agent_type(self) -> str:
        return "outliner"

    def _build_user_prompt(self, input_data: dict, context: dict = None) -> str:
        return OUTLINER_USER_PROMPT_TEMPLATE.format(
            title=input_data.get('title', ''),
            subject=input_data.get('subject', ''),
            target_audience=input_data.get('target_audience', ''),
            level=input_data.get('level', ''),
            total_chapters=input_data.get('total_chapters', 10),
            chapter_word_count=input_data.get('chapter_word_count', 5000),
            style=input_data.get('style', '学术'),
            curriculum_standard=input_data.get('curriculum_standard', ''),
        )

    def _parse_output(self, llm_output: str, input_data: dict) -> dict:
        return {
            'outline_text': llm_output,
            'title': input_data.get('title', ''),
            'subject': input_data.get('subject', ''),
        }
