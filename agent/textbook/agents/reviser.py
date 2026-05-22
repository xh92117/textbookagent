from .base import TextbookBaseAgent
from ..prompts.reviser_prompts import REVISER_SYSTEM_PROMPT, REVISER_USER_PROMPT_TEMPLATE


class ReviserAgent(TextbookBaseAgent):
    def get_system_prompt(self) -> str:
        return REVISER_SYSTEM_PROMPT

    def get_agent_type(self) -> str:
        return "reviser"

    def _build_user_prompt(self, input_data: dict, context: dict = None) -> str:
        issues = input_data.get('issues', [])
        if isinstance(issues, list):
            issues_str = '\n'.join(
                f"- [{i.get('level', '')}] {i.get('description', '')} → {i.get('suggestion', '')}"
                for i in issues
            )
        else:
            issues_str = str(issues)
        return REVISER_USER_PROMPT_TEMPLATE.format(
            content=input_data.get('content', ''),
            score=input_data.get('score', 0),
            issues=issues_str,
            mode=input_data.get('mode', 'spot-fix'),
            writing_spec=input_data.get('writing_spec', ''),
        )

    def _parse_output(self, llm_output: str, input_data: dict) -> dict:
        return {
            'revised_content': llm_output,
            'chapter_number': input_data.get('chapter_number', 0),
        }
