from .base import TextbookBaseAgent
from ..prompts.reviser_prompts import POLISHER_SYSTEM_PROMPT, POLISHER_USER_PROMPT_TEMPLATE


class PolisherAgent(TextbookBaseAgent):
    def get_system_prompt(self) -> str:
        return POLISHER_SYSTEM_PROMPT

    def get_agent_type(self) -> str:
        return "polisher"

    def _build_user_prompt(self, input_data: dict, context: dict = None) -> str:
        return POLISHER_USER_PROMPT_TEMPLATE.format(
            content=input_data.get('content', ''),
            style=input_data.get('style', '学术'),
        )

    def _parse_output(self, llm_output: str, input_data: dict) -> dict:
        return {
            'polished_content': llm_output,
            'chapter_number': input_data.get('chapter_number', 0),
        }
