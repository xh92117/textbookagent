import os
import json
from typing import Dict, Optional
from datetime import datetime


class TruthFileManager:
    TRUTH_FILES = {
        'outline': 'outline/outline.md',
        'knowledge_graph': 'outline/knowledge_graph.md',
        'terminology': 'outline/terminology.md',
        'current_state': 'state/current_state.md',
        'chapter_summaries': 'state/chapter_summaries.md',
        'concept_ledger': 'state/concept_ledger.md',
        'cross_references': 'state/cross_references.md',
        'progress': 'state/progress.md',
        'status': 'state/status.json',
        'research_evidence': 'state/research_evidence.md',
    }

    def __init__(self, book_dir: str):
        self.book_dir = book_dir
        self._ensure_dirs()

    def _ensure_dirs(self):
        dirs = ['outline', 'state', 'chapters', 'assets/images', 'assets/charts', 'output', 'snapshots']
        for d in dirs:
            os.makedirs(os.path.join(self.book_dir, d), exist_ok=True)

    def read(self, file_key: str) -> str:
        filepath = os.path.join(self.book_dir, self.TRUTH_FILES[file_key])
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def write(self, file_key: str, content: str):
        filepath = os.path.join(self.book_dir, self.TRUTH_FILES[file_key])
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def read_chapter(self, chapter_num: int) -> str:
        filepath = os.path.join(self.book_dir, 'chapters', f'chapter_{chapter_num:02d}.md')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def write_chapter(self, chapter_num: int, content: str):
        filepath = os.path.join(self.book_dir, 'chapters', f'chapter_{chapter_num:02d}.md')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def list_chapters(self) -> list:
        chapters_dir = os.path.join(self.book_dir, 'chapters')
        if not os.path.exists(chapters_dir):
            return []
        files = sorted(os.listdir(chapters_dir))
        return [f for f in files if f.startswith('chapter_') and f.endswith('.md')]

    def list_completed_chapter_numbers(self) -> list:
        chapter_numbers = []
        for filename in self.list_chapters():
            try:
                chapter_numbers.append(int(filename.replace('chapter_', '').replace('.md', '')))
            except ValueError:
                continue
        return sorted(chapter_numbers)

    def save_snapshot(self, snapshot_name: str = ""):
        if not snapshot_name:
            snapshot_name = datetime.now().strftime('snapshot_%Y%m%d_%H%M%S')
        snapshot_dir = os.path.join(self.book_dir, 'snapshots', snapshot_name)
        os.makedirs(snapshot_dir, exist_ok=True)
        for key, rel_path in self.TRUTH_FILES.items():
            src = os.path.join(self.book_dir, rel_path)
            if os.path.exists(src):
                dst = os.path.join(snapshot_dir, rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(src, 'r', encoding='utf-8') as f:
                    content = f.read()
                with open(dst, 'w', encoding='utf-8') as f:
                    f.write(content)

    def get_progress(self) -> Dict:
        progress_str = self.read('progress')
        if not progress_str:
            return {'completed_chapters': 0, 'total_chapters': 0, 'percentage': 0}
        try:
            return json.loads(progress_str)
        except json.JSONDecodeError:
            return {'completed_chapters': 0, 'total_chapters': 0, 'percentage': 0}

    def update_progress(self, completed: int, total: int):
        progress = {
            'completed_chapters': completed,
            'total_chapters': total,
            'percentage': round(completed / total * 100, 1) if total > 0 else 0,
            'updated_at': datetime.now().isoformat(),
        }
        self.write('progress', json.dumps(progress, ensure_ascii=False, indent=2))
        self.update_status(
            total_chapters=total,
            current_chapter=completed if completed > 0 else None,
            current_phase='progress_updated',
            run_status='running' if total == 0 or completed < total else 'completed',
        )

    def get_status(self) -> Dict:
        status_str = self.read('status')
        if not status_str:
            return {}
        try:
            return json.loads(status_str)
        except json.JSONDecodeError:
            return {}

    def update_status(
        self,
        total_chapters: int = 0,
        current_chapter: Optional[int] = None,
        current_phase: str = "",
        run_status: str = "running",
        extra: Optional[Dict] = None,
    ) -> Dict:
        progress = self.get_progress()
        completed_chapters = self.list_completed_chapter_numbers()
        total = total_chapters or progress.get('total_chapters', 0) or 0
        payload = {
            'version': 'textbook-status-v1',
            'book_dir': self.book_dir,
            'status': run_status,
            'current_chapter': current_chapter,
            'current_phase': current_phase,
            'completed_chapters': completed_chapters,
            'latest_completed_chapter': completed_chapters[-1] if completed_chapters else None,
            'total_chapters': total,
            'progress': progress,
            'files': {
                'outline': self.TRUTH_FILES['outline'],
                'chapter_summaries': self.TRUTH_FILES['chapter_summaries'],
                'progress': self.TRUTH_FILES['progress'],
                'status': self.TRUTH_FILES['status'],
                'pipeline_checkpoints': 'state/pipeline_checkpoints',
            },
            'updated_at': datetime.now().isoformat(),
        }
        if extra:
            payload.update(extra)
        self.write('status', json.dumps(payload, ensure_ascii=False, indent=2))
        return payload

    def append_chapter_summary(self, chapter_num: int, title: str, summary: str):
        current = self.read('chapter_summaries')
        entry = f"## 第{chapter_num}章 {title}\n{summary}\n\n"
        self.write('chapter_summaries', current + entry)

    def update_terminology(self, terms: Dict[str, str]):
        current = self.read('terminology')
        lines = current.split('\n') if current else []
        existing = {}
        for line in lines:
            if '|' in line and not line.startswith('|--') and not line.startswith('| 术语'):
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3:
                    existing[parts[1]] = parts[2]
        existing.update(terms)
        header = "| 术语 | 定义 |\n|------|------|\n"
        rows = "".join(f"| {k} | {v} |\n" for k, v in sorted(existing.items()))
        self.write('terminology', header + rows)

    def get_terminology(self) -> Dict[str, str]:
        content = self.read('terminology')
        if not content:
            return {}
        terms = {}
        for line in content.split('\n'):
            if '|' in line and not line.startswith('|--') and not line.startswith('| 术语'):
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3 and parts[1] and parts[2]:
                    terms[parts[1]] = parts[2]
        return terms
