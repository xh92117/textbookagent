import json
from .base import TextbookBaseAgent
from ..metrics import measure_content
from ..prompts.reviewer_prompts import (
    REVIEWER_OUTLINE_SYSTEM_PROMPT, REVIEWER_CHAPTER_SYSTEM_PROMPT,
    REVIEWER_USER_PROMPT_TEMPLATE,
)


class ReviewerAgent(TextbookBaseAgent):
    def get_system_prompt(self) -> str:
        mode = getattr(self, '_review_mode', 'chapter')
        if mode == 'outline':
            return REVIEWER_OUTLINE_SYSTEM_PROMPT
        return REVIEWER_CHAPTER_SYSTEM_PROMPT

    def get_agent_type(self) -> str:
        return "reviewer"

    def set_review_mode(self, mode: str):
        self._review_mode = mode

    def _build_user_prompt(self, input_data: dict, context: dict = None) -> str:
        mode = getattr(self, '_review_mode', 'chapter')
        mode_label = '大纲' if mode == 'outline' else '章节'
        dimension_count = '9' if mode == 'outline' else '24'
        metrics = input_data.get('content_metrics')
        if not metrics:
            metrics = measure_content(input_data.get('content', '')).to_dict()
        return REVIEWER_USER_PROMPT_TEMPLATE.format(
            mode=mode,
            mode_label=mode_label,
            title=input_data.get('title', ''),
            item_label=input_data.get('item_label', ''),
            content=input_data.get('content', ''),
            outline_context=input_data.get('outline_context', ''),
            dimension_count=dimension_count,
            writing_spec=input_data.get('writing_spec', ''),
            content_metrics=json.dumps(metrics, ensure_ascii=False, indent=2),
        )

    def _parse_output(self, llm_output: str, input_data: dict) -> dict:
        try:
            json_str = llm_output
            if '```json' in llm_output:
                json_str = llm_output.split('```json')[1].split('```')[0]
            elif '```' in llm_output:
                json_str = llm_output.split('```')[1].split('```')[0]
            result = json.loads(json_str.strip())
            return {
                'passed': result.get('passed', False),
                'score': result.get('score', 0),
                'dimensions': result.get('dimensions', []),
                'issues': result.get('issues', []),
                'raw_output': llm_output,
            }
        except (json.JSONDecodeError, IndexError):
            return {
                'passed': False,
                'score': 0,
                'dimensions': [],
                'issues': [{'level': 'critical', 'description': 'Failed to parse review output'}],
                'raw_output': llm_output,
            }
