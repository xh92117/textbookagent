from pathlib import Path


def _skill_text(name: str) -> str:
    return Path("skills", name, "SKILL.md").read_text(encoding="utf-8")


def test_chapter_skill_uses_current_canonical_tools_only():
    text = _skill_text("chapter")

    assert "textbook_chapter" in text
    assert "Repair mode may use `edit` or `write`" in text
    assert "Do not use `bash`" in text
    assert "write(\"chapters/" not in text
    assert "bash" not in text.split("---", 2)[1]


def test_fullbook_skill_requires_existing_start_pipeline_confirmation_flow():
    text = _skill_text("fullbook")

    assert "start_pipeline" in text
    assert "quality is not fully controllable" in text
    assert "Do not use `bash`, `write`, or manual scripts" in text


def test_outline_and_review_skills_use_existing_textbook_tools():
    outline = _skill_text("outline")
    review = _skill_text("review")

    assert "textbook_outline" in outline
    assert "Do not use `write`, `edit`, or `bash`" in outline
    assert "textbook_chapter" in review
    assert "Do not modify reviewed content" in review
