from .base import TextbookBaseAgent


class ComposerAgent(TextbookBaseAgent):
    def get_system_prompt(self) -> str:
        return (
            "你是教材上下文组装智能体。只整理当前章节写作所需材料：大纲、已完成章节摘要、术语、状态和当前章节信息。"
            "不要写正文，不要改大纲，不要补充未提供的事实。输出应简洁、分区清楚、便于 WriterAgent 直接使用。"
        )

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
