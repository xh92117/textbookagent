import os
import json
import hashlib
import re
from typing import Dict, Optional
from datetime import datetime


class TruthFileManager:
    STATUS_PHASE_ORDER = {
        'pipeline_started': 0,
        'outline': 10,
        'review_outline': 20,
        'chapter_actions_planned': 90,
        'read_outline': 100,
        'retrieve_knowledge': 110,
        'build_context': 120,
        'write_chapter': 130,
        'route_visual_assets': 140,
        'review_chapter': 150,
        'revise_chapter': 160,
        'polish_chapter': 170,
        'persist_chapter': 180,
        'progress_updated': 185,
        'pipeline_completed': 1000,
    }
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
        'outline_review_state': 'state/outline_review.json',
        'research_evidence': 'state/research_evidence.md',
        'harness': 'harness.md',
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

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256((content or "").encode('utf-8')).hexdigest()

    def get_outline_review_state(self) -> Dict:
        raw = self.read('outline_review_state')
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def mark_outline_reviewed(self, outline_text: str, review_result: Optional[Dict] = None) -> Dict:
        review_result = review_result or {}
        issues = review_result.get('issues') or []
        payload = {
            'version': 'outline-review-state-v1',
            'status': 'reviewed',
            'outline_hash': self.content_hash(outline_text),
            'outline_chars': len(outline_text or ''),
            'score': review_result.get('score', 0),
            'issues_count': len(issues) if isinstance(issues, list) else 0,
            'reviewed_at': datetime.now().isoformat(),
        }
        self.write('outline_review_state', json.dumps(payload, ensure_ascii=False, indent=2))
        return payload

    def is_outline_review_current(self, outline_text: str = "") -> bool:
        if not outline_text:
            outline_text = self.read('outline')
        if not outline_text.strip():
            return False
        state = self.get_outline_review_state()
        return (
            state.get('status') == 'reviewed'
            and state.get('outline_hash') == self.content_hash(outline_text)
        )

    def invalidate_outline_review(self, reason: str = "outline_updated") -> Dict:
        outline_text = self.read('outline')
        payload = {
            'version': 'outline-review-state-v1',
            'status': 'stale',
            'outline_hash': self.content_hash(outline_text),
            'outline_chars': len(outline_text or ''),
            'reason': reason,
            'updated_at': datetime.now().isoformat(),
        }
        self.write('outline_review_state', json.dumps(payload, ensure_ascii=False, indent=2))
        return payload

    def infer_outline_review_from_reports(self) -> bool:
        outline_path = os.path.join(self.book_dir, self.TRUTH_FILES['outline'])
        outline_text = self.read('outline')
        if not outline_text.strip() or not os.path.exists(outline_path):
            return False
        outline_mtime = os.path.getmtime(outline_path)
        report_dirs = [
            os.path.join(self.book_dir, 'outline'),
            os.path.join(self.book_dir, 'state'),
        ]
        latest_report = ""
        latest_mtime = 0.0
        for report_dir in report_dirs:
            if not os.path.isdir(report_dir):
                continue
            for filename in os.listdir(report_dir):
                lower = filename.lower()
                if 'review' not in lower or not lower.endswith(('.md', '.json')):
                    continue
                path = os.path.join(report_dir, filename)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if mtime >= outline_mtime and mtime > latest_mtime:
                    latest_report = os.path.relpath(path, self.book_dir).replace('\\', '/')
                    latest_mtime = mtime
        if not latest_report:
            return False
        payload = {
            'version': 'outline-review-state-v1',
            'status': 'reviewed',
            'outline_hash': self.content_hash(outline_text),
            'outline_chars': len(outline_text),
            'source': 'inferred_from_review_report',
            'review_report': latest_report,
            'reviewed_at': datetime.fromtimestamp(latest_mtime).isoformat(),
        }
        self.write('outline_review_state', json.dumps(payload, ensure_ascii=False, indent=2))
        return True

    def read_chapter(self, chapter_num: int) -> str:
        for filepath in self._chapter_path_candidates(chapter_num):
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return f.read()
        return ""

    def _chapter_path_candidates(self, chapter_num: int) -> list:
        chapters_dir = os.path.join(self.book_dir, 'chapters')
        candidates = []
        if os.path.isdir(chapters_dir):
            pattern = re.compile(r'^chapter_0*(\d+)\.md$', re.IGNORECASE)
            for filename in sorted(os.listdir(chapters_dir)):
                match = pattern.match(filename)
                if match and int(match.group(1)) == int(chapter_num):
                    candidates.append(os.path.join(chapters_dir, filename))
        candidates.extend([
            os.path.join(chapters_dir, f'chapter_{chapter_num:03d}.md'),
            os.path.join(chapters_dir, f'chapter_{chapter_num:02d}.md'),
        ])
        return list(dict.fromkeys(candidates))

    def _chapter_path(self, chapter_num: int) -> str:
        for filepath in self._chapter_path_candidates(chapter_num):
            if os.path.exists(filepath):
                return filepath
        return self._chapter_path_candidates(chapter_num)[0]

    def _chapter_meta_path_candidates(self, chapter_num: int) -> list:
        chapters_dir = os.path.join(self.book_dir, 'chapters')
        candidates = []
        if os.path.isdir(chapters_dir):
            pattern = re.compile(r'^chapter_0*(\d+)_meta\.json$', re.IGNORECASE)
            for filename in sorted(os.listdir(chapters_dir)):
                match = pattern.match(filename)
                if match and int(match.group(1)) == int(chapter_num):
                    candidates.append(os.path.join(chapters_dir, filename))
        candidates.extend([
            os.path.join(chapters_dir, f'chapter_{chapter_num:03d}_meta.json'),
            os.path.join(chapters_dir, f'chapter_{chapter_num:02d}_meta.json'),
        ])
        return list(dict.fromkeys(candidates))

    def _chapter_meta_path(self, chapter_num: int) -> str:
        for filepath in self._chapter_meta_path_candidates(chapter_num):
            if os.path.exists(filepath):
                return filepath
        return self._chapter_meta_path_candidates(chapter_num)[0]

    def write_chapter(self, chapter_num: int, content: str):
        filepath = self._chapter_path(chapter_num)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def chapter_metadata_path(self, chapter_num: int) -> str:
        return self._chapter_meta_path(chapter_num)

    def get_chapter_metadata(self, chapter_num: int) -> Dict:
        path = self.chapter_metadata_path(chapter_num)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def is_chapter_complete(self, chapter_num: int, min_chars: int = 50) -> bool:
        content = self.read_chapter(chapter_num)
        if len((content or "").strip()) < min_chars:
            return False
        meta = self.get_chapter_metadata(chapter_num)
        if not meta:
            # Legacy chapters did not always write metadata. Treat a substantial
            # chapter body as complete for backward compatibility.
            return True
        if meta.get('status') and meta.get('status') != 'completed':
            return False
        content_hash = meta.get('content_hash')
        if content_hash and content_hash != self.content_hash(content):
            return False
        return True

    def list_chapters(self) -> list:
        chapters_dir = os.path.join(self.book_dir, 'chapters')
        if not os.path.exists(chapters_dir):
            return []
        by_num = {}
        pattern = re.compile(r'^chapter_0*(\d+)\.md$', re.IGNORECASE)
        for filename in sorted(os.listdir(chapters_dir)):
            match = pattern.match(filename)
            if not match:
                continue
            num = int(match.group(1))
            by_num.setdefault(num, filename)
        return [by_num[num] for num in sorted(by_num)]

    def list_completed_chapter_numbers(self, min_chars: int = 1) -> list:
        chapter_numbers = []
        for filename in self.list_chapters():
            try:
                chapter_num = int(re.match(r'^chapter_0*(\d+)\.md$', filename, re.IGNORECASE).group(1))
            except (AttributeError, ValueError):
                continue
            if self.is_chapter_complete(chapter_num, min_chars=min_chars):
                chapter_numbers.append(chapter_num)
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
        previous = self.get_status()
        previous_chapter = previous.get('current_chapter')
        previous_phase = previous.get('current_phase') or ""
        previous_rank = int(previous.get('phase_rank', self.STATUS_PHASE_ORDER.get(previous_phase, -1)) or -1)
        current_rank = self.STATUS_PHASE_ORDER.get(current_phase, previous_rank)
        regression = False
        same_chapter = (
            current_chapter is not None
            and previous_chapter is not None
            and int(current_chapter) == int(previous_chapter)
        )
        next_chapter = (
            current_chapter is not None
            and previous_chapter is not None
            and int(current_chapter) > int(previous_chapter)
        )
        if previous.get('status') == 'completed' and run_status != 'completed':
            regression = True
        elif same_chapter and current_rank < previous_rank:
            regression = True
        elif (
            previous_rank >= self.STATUS_PHASE_ORDER['chapter_actions_planned']
            and current_rank < previous_rank
            and not next_chapter
        ):
            # Once chapter work has begun for a textbook, status updates must
            # not silently jump back to outline/review/planning. This catches
            # free-form agent loops where the model re-enters "understand task"
            # or "regenerate outline" after writing has already started.
            regression = True
        if regression:
            current_phase = previous_phase
            current_rank = previous_rank
            current_chapter = previous_chapter
            run_status = previous.get('status', run_status)

        payload = {
            'version': 'textbook-status-v1',
            'book_dir': self.book_dir,
            'status': run_status,
            'current_chapter': current_chapter,
            'current_phase': current_phase,
            'phase_rank': current_rank,
            'regression_blocked': regression,
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
