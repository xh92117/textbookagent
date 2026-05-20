from typing import List, Callable, Optional


class ChapterScheduler:
    def __init__(self, total_chapters: int, on_progress: Callable = None):
        self.total_chapters = total_chapters
        self.on_progress = on_progress
        self.completed = []
        self.current = 0

    def get_next_chapter(self) -> Optional[int]:
        while self.current < self.total_chapters:
            self.current += 1
            if self.current not in self.completed:
                if self.on_progress:
                    self.on_progress(self.current, self.total_chapters)
                return self.current
        return None

    def mark_completed(self, chapter_num: int):
        if chapter_num not in self.completed:
            self.completed.append(chapter_num)

    def get_progress(self) -> dict:
        return {
            'completed': len(self.completed),
            'total': self.total_chapters,
            'percentage': round(len(self.completed) / self.total_chapters * 100, 1) if self.total_chapters > 0 else 0,
        }

    def get_pending_chapters(self) -> List[int]:
        return [i for i in range(1, self.total_chapters + 1) if i not in self.completed]
