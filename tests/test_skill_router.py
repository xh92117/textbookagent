from agent.prompt.builder import _build_skills_section
from agent.skills.router import route_skills
from agent.skills.types import Skill, SkillEntry, SkillMetadata


def _entry(name: str, description: str = "") -> SkillEntry:
    return SkillEntry(
        skill=Skill(
            name=name,
            description=description,
            file_path=f"/tmp/{name}/SKILL.md",
            base_dir=f"/tmp/{name}",
            source="builtin",
            content="",
        ),
        metadata=SkillMetadata(),
    )


def test_skill_router_selects_chapter_skill_for_chapter_work():
    entries = [
        _entry("textbook-chapter", "Write or edit textbook chapters"),
        _entry("textbook-wordgen", "Export Word documents"),
        _entry("multi-search-engine", "Search web sources"),
    ]

    route = route_skills("Please continue writing chapter 2 of the textbook.", entries)

    assert route.task_type == "chapter"
    assert route.selected_skills == ["textbook-chapter"]
    assert "textbook-wordgen" in route.omitted_skills
    assert "Skill routing policy" in route.prompt


def test_skill_router_selects_existing_chapter_skill_for_chinese_fix_request():
    entries = [
        _entry("textbook-chapter", "Write, continue, rewrite, or repair textbook chapters"),
        _entry("textbook-outline", "Create or adjust textbook outlines"),
        _entry("textbook-fullbook", "Run the full textbook pipeline"),
    ]

    route = route_skills("修复第1章重复标题，不要重写整本教材", entries)

    assert route.task_type == "chapter"
    assert route.selected_skills == ["textbook-chapter"]
    assert "read the selected SKILL.md" in route.prompt


def test_skill_router_selects_existing_fullbook_skill_for_pipeline_request():
    entries = [
        _entry("textbook-chapter", "Write a single chapter"),
        _entry("textbook-fullbook", "Run the full textbook pipeline"),
    ]

    route = route_skills("启动教材自动编制管线", entries)

    assert route.task_type == "fullbook"
    assert route.selected_skills == ["textbook-fullbook"]


def test_skill_router_selects_at_most_two_specific_skills():
    entries = [
        _entry("textbook-imagegen", "Generate textbook figures and diagrams"),
        _entry("textbook-sandbox", "Run code and create computed charts"),
        _entry("textbook-review", "Review textbook quality"),
    ]

    route = route_skills(
        "Create a diagram and run code to generate a data chart for this section.",
        entries,
        max_skills=2,
    )

    assert len(route.selected_skills) <= 2
    assert "textbook-imagegen" in route.selected_skills
    assert "textbook-sandbox" in route.selected_skills


def test_skill_router_returns_no_skill_when_unclear():
    entries = [_entry("textbook-chapter"), _entry("textbook-outline")]

    route = route_skills("Hello, help me think about this.", entries)

    assert route.task_type == "general"
    assert route.selected_skills == []
    assert "Visible skills for this turn: none" in route.prompt


class _FakeSkillManager:
    def build_skills_prompt(self, skill_filter=None):
        return "ALL SKILLS" if skill_filter is None else ",".join(skill_filter)


def test_prompt_builder_empty_skill_filter_does_not_show_all_skills():
    lines = _build_skills_section(_FakeSkillManager(), tools=[], language="zh", skill_filter=[])
    text = "\n".join(lines)

    assert "ALL SKILLS" not in text
    assert "did not select a specific skill" in text
