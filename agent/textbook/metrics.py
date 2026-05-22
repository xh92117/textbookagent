import re
from dataclasses import asdict, dataclass


_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_VISUAL_MARKER_RE = re.compile(r"\[(?:图表|图|Chart|chart|插图|图片|Image|image|Illustration|illustration)\s*[:：]\s*[^\]]+?\]")
_MARKDOWN_LINK_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\)")
_MARKDOWN_SYNTAX_RE = re.compile(r"[#>*_`~\-\|\[\]\(\)]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_EN_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_+-]*\b")


@dataclass
class ContentMetrics:
    content_chars: int = 0
    effective_chars: int = 0
    cjk_chars: int = 0
    english_words: int = 0
    code_lines: int = 0
    visual_markers: int = 0

    @property
    def effective_word_count(self) -> int:
        # English technical terms are useful content, but should not inflate a
        # Chinese textbook target at 1 char per letter. Count them as words.
        return self.cjk_chars + self.english_words

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["effective_word_count"] = self.effective_word_count
        return payload


def strip_non_body_blocks(markdown_text: str) -> str:
    text = markdown_text or ""
    text = re.sub(r"(?s)^###\s*PRE_WRITE_CHECK.*?(?=^###\s*CHAPTER_CONTENT|\Z)", "", text, flags=re.MULTILINE)
    text = re.sub(r"(?s)^###\s*VISUAL_ASSETS.*?(?=^###\s*CHAPTER_CONTENT|\Z)", "", text, flags=re.MULTILINE)
    text = text.replace("### CHAPTER_CONTENT", "")
    text = _FENCED_CODE_RE.sub("", text)
    text = _VISUAL_MARKER_RE.sub("", text)
    text = _MARKDOWN_LINK_RE.sub("", text)
    text = re.sub(r"(?m)^\s*\|.*\|\s*$", "", text)
    text = _MARKDOWN_SYNTAX_RE.sub("", text)
    return text


def measure_content(markdown_text: str) -> ContentMetrics:
    raw = markdown_text or ""
    code_lines = sum(block.group(0).count("\n") + 1 for block in _FENCED_CODE_RE.finditer(raw))
    visual_markers = len(_VISUAL_MARKER_RE.findall(raw))
    body = strip_non_body_blocks(raw)
    cjk_chars = len(_CJK_RE.findall(body))
    english_words = len(_EN_WORD_RE.findall(body))
    effective_chars = len(re.sub(r"\s+", "", body))
    return ContentMetrics(
        content_chars=len(raw),
        effective_chars=effective_chars,
        cjk_chars=cjk_chars,
        english_words=english_words,
        code_lines=code_lines,
        visual_markers=visual_markers,
    )
