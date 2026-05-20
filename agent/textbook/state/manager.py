import os
import json
from typing import Dict, Optional, List
from .truth_files import TruthFileManager


class TextbookMemoryManager:
    def __init__(self, workspace_dir: str, base_memory_manager=None, workspace_root: str = None):
        self.workspace_dir = workspace_dir
        self.textbooks_dir = workspace_dir
        if workspace_root:
            self.workspace_root = workspace_root
        elif os.path.basename(os.path.normpath(workspace_dir)).lower() == "textbooks":
            self.workspace_root = os.path.dirname(os.path.normpath(workspace_dir))
        else:
            self.workspace_root = workspace_dir
        self.base_memory = base_memory_manager
        self._book_managers: Dict[str, TruthFileManager] = {}

    def _get_book_dir(self, book_id: str) -> str:
        return os.path.join(self.workspace_dir, book_id)

    def get_truth_manager(self, book_id: str) -> TruthFileManager:
        if book_id not in self._book_managers:
            self._book_managers[book_id] = TruthFileManager(self._get_book_dir(book_id))
        return self._book_managers[book_id]

    def save_textbook_state(self, book_id: str, state: dict):
        mgr = self.get_truth_manager(book_id)
        if 'current_state' in state:
            mgr.write('current_state', state['current_state'])
        if 'progress' in state:
            mgr.write('progress', json.dumps(state['progress'], ensure_ascii=False, indent=2))

    def load_textbook_state(self, book_id: str) -> dict:
        mgr = self.get_truth_manager(book_id)
        progress_str = mgr.read('progress')
        return {
            'current_state': mgr.read('current_state'),
            'progress': json.loads(progress_str) if progress_str else {},
            'chapter_summaries': mgr.read('chapter_summaries'),
            'terminology': mgr.get_terminology(),
        }

    def get_chapter_summary(self, book_id: str, chapter_num: int) -> str:
        mgr = self.get_truth_manager(book_id)
        content = mgr.read_chapter(chapter_num)
        if not content:
            return ""
        lines = content.split('\n')
        summary_lines = []
        in_summary = False
        for line in lines:
            if '本章小结' in line or '## 小结' in line:
                in_summary = True
                continue
            if in_summary:
                if line.startswith('## ') and '小结' not in line:
                    break
                summary_lines.append(line)
        return '\n'.join(summary_lines).strip()

    def get_terminology(self, book_id: str) -> Dict[str, str]:
        mgr = self.get_truth_manager(book_id)
        return mgr.get_terminology()

    def update_terminology(self, book_id: str, terms: Dict[str, str]):
        mgr = self.get_truth_manager(book_id)
        mgr.update_terminology(terms)

    def get_cross_references(self, book_id: str) -> List[str]:
        mgr = self.get_truth_manager(book_id)
        content = mgr.read('cross_references')
        if not content:
            return []
        return [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]

    def search_memory(self, query: str, limit: int = 5) -> List[str]:
        if self.base_memory:
            try:
                results = self.base_memory.search(query, limit=limit)
                return results if results else []
            except Exception:
                return []
        return []
