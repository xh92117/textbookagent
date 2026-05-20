import os
import json
import shutil
import hashlib
import re
from datetime import datetime
from typing import List, Optional


class ChapterPersistence:
    def __init__(self, book_dir: str):
        self.book_dir = book_dir
        self.chapters_dir = os.path.join(book_dir, 'chapters')
        self.snapshots_dir = os.path.join(book_dir, 'snapshots')
        os.makedirs(self.chapters_dir, exist_ok=True)
        os.makedirs(self.snapshots_dir, exist_ok=True)

    def save_chapter(self, chapter_num: int, content: str, metadata: dict = None):
        filepath = self._chapter_path(chapter_num)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        meta = dict(metadata or {})
        meta.setdefault('status', 'completed')
        meta['content_hash'] = hashlib.sha256((content or "").encode('utf-8')).hexdigest()
        meta['content_chars'] = len(content or "")
        meta['saved_at'] = datetime.now().isoformat()
        meta_path = self._chapter_meta_path(chapter_num)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def load_chapter(self, chapter_num: int) -> str:
        for filepath in self._chapter_path_candidates(chapter_num):
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return f.read()
        return ""

    def _chapter_path_candidates(self, chapter_num: int) -> list:
        candidates = []
        if os.path.isdir(self.chapters_dir):
            pattern = re.compile(r'^chapter_0*(\d+)\.md$', re.IGNORECASE)
            for filename in sorted(os.listdir(self.chapters_dir)):
                match = pattern.match(filename)
                if match and int(match.group(1)) == int(chapter_num):
                    candidates.append(os.path.join(self.chapters_dir, filename))
        candidates.extend([
            os.path.join(self.chapters_dir, f'chapter_{chapter_num:03d}.md'),
            os.path.join(self.chapters_dir, f'chapter_{chapter_num:02d}.md'),
        ])
        return list(dict.fromkeys(candidates))

    def _chapter_path(self, chapter_num: int) -> str:
        for filepath in self._chapter_path_candidates(chapter_num):
            if os.path.exists(filepath):
                return filepath
        return self._chapter_path_candidates(chapter_num)[0]

    def _chapter_meta_path_candidates(self, chapter_num: int) -> list:
        candidates = []
        if os.path.isdir(self.chapters_dir):
            pattern = re.compile(r'^chapter_0*(\d+)_meta\.json$', re.IGNORECASE)
            for filename in sorted(os.listdir(self.chapters_dir)):
                match = pattern.match(filename)
                if match and int(match.group(1)) == int(chapter_num):
                    candidates.append(os.path.join(self.chapters_dir, filename))
        candidates.extend([
            os.path.join(self.chapters_dir, f'chapter_{chapter_num:03d}_meta.json'),
            os.path.join(self.chapters_dir, f'chapter_{chapter_num:02d}_meta.json'),
        ])
        return list(dict.fromkeys(candidates))

    def _chapter_meta_path(self, chapter_num: int) -> str:
        for filepath in self._chapter_meta_path_candidates(chapter_num):
            if os.path.exists(filepath):
                return filepath
        return self._chapter_meta_path_candidates(chapter_num)[0]

    def load_chapter_metadata(self, chapter_num: int) -> dict:
        for meta_path in self._chapter_meta_path_candidates(chapter_num):
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        return {}

    def list_chapters(self) -> List[int]:
        if not os.path.exists(self.chapters_dir):
            return []
        chapters = []
        pattern = re.compile(r'^chapter_0*(\d+)\.md$', re.IGNORECASE)
        for f in os.listdir(self.chapters_dir):
            match = pattern.match(f)
            if match:
                chapters.append(int(match.group(1)))
        return sorted(chapters)

    def create_snapshot(self, snapshot_name: str = "") -> str:
        if not snapshot_name:
            snapshot_name = datetime.now().strftime('snapshot_%Y%m%d_%H%M%S')
        snapshot_dir = os.path.join(self.snapshots_dir, snapshot_name)
        if os.path.exists(snapshot_dir):
            shutil.rmtree(snapshot_dir)
        shutil.copytree(self.chapters_dir, os.path.join(snapshot_dir, 'chapters'))
        return snapshot_dir
