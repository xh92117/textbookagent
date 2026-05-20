import os
import json
import shutil
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
        filepath = os.path.join(self.chapters_dir, f'chapter_{chapter_num:02d}.md')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        if metadata:
            meta_path = os.path.join(self.chapters_dir, f'chapter_{chapter_num:02d}_meta.json')
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

    def load_chapter(self, chapter_num: int) -> str:
        filepath = os.path.join(self.chapters_dir, f'chapter_{chapter_num:02d}.md')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def load_chapter_metadata(self, chapter_num: int) -> dict:
        meta_path = os.path.join(self.chapters_dir, f'chapter_{chapter_num:02d}_meta.json')
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def list_chapters(self) -> List[int]:
        if not os.path.exists(self.chapters_dir):
            return []
        chapters = []
        for f in os.listdir(self.chapters_dir):
            if f.startswith('chapter_') and f.endswith('.md'):
                try:
                    num = int(f.replace('chapter_', '').replace('.md', ''))
                    chapters.append(num)
                except ValueError:
                    pass
        return sorted(chapters)

    def create_snapshot(self, snapshot_name: str = "") -> str:
        if not snapshot_name:
            snapshot_name = datetime.now().strftime('snapshot_%Y%m%d_%H%M%S')
        snapshot_dir = os.path.join(self.snapshots_dir, snapshot_name)
        if os.path.exists(snapshot_dir):
            shutil.rmtree(snapshot_dir)
        shutil.copytree(self.chapters_dir, os.path.join(snapshot_dir, 'chapters'))
        return snapshot_dir
