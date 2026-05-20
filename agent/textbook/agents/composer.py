from .base import TextbookBaseAgent


class ComposerAgent(TextbookBaseAgent):
    def get_system_prompt(self) -> str:
        return "你是一位教材上下文组装专家。你的任务是根据当前章节信息，收集和组装写作所需的全部上下文。"

    def get_agent_type(self) -> str:
        return "composer"

    def _build_user_prompt(self, input_data: dict, context: dict = None) -> str:
        parts = []
        if input_data.get('outline'):
            parts.append(f"## 教材大纲\n{input_data['outline']}")
        if input_data.get('chapter_summaries'):
            parts.append(f"## 已完成章节摘要\n{input_data['chapter_summaries']}")
        if input_data.get('terminology'):
            terms = input_data['terminology']
            if isinstance(terms, dict):
                terms_str = '\n'.join(f'- **{k}**: {v}' for k, v in terms.items())
                parts.append(f"## 术语表\n{terms_str}")
            else:
                parts.append(f"## 术语表\n{terms}")
        if input_data.get('current_state'):
            parts.append(f"## 当前状态\n{input_data['current_state']}")
        if input_data.get('current_chapter'):
            parts.append(f"## 当前章节\n{input_data['current_chapter']}")
        return '\n\n'.join(parts) if parts else str(input_data)

    def _parse_output(self, llm_output: str, input_data: dict) -> dict:
        return {
            'context_package': llm_output,
            'chapter_number': input_data.get('chapter_number', 0),
        }
