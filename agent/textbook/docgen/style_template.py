from dataclasses import dataclass, field
from typing import Dict

@dataclass
class StyleTemplate:
    name: str = "academic"
    page_size: str = "A4"
    margin_top: float = 2.54
    margin_bottom: float = 2.54
    margin_left: float = 3.17
    margin_right: float = 3.17
    heading1_font: str = "黑体"
    heading1_size: int = 16
    heading1_bold: bool = True
    heading1_alignment: str = "center"
    heading2_font: str = "黑体"
    heading2_size: int = 16
    heading2_bold: bool = True
    heading3_font: str = "黑体"
    heading3_size: int = 16
    heading3_bold: bool = False
    body_font: str = "仿宋"
    body_size: int = 12
    body_line_spacing: float = 1.5
    body_first_line_indent: int = 2
    code_font: str = "Consolas"
    code_size: int = 10
    code_background: str = "F5F5F5"
    caption_font: str = "仿宋"
    caption_size: float = 10.5
    caption_alignment: str = "center"

ACADEMIC_TEMPLATE = StyleTemplate(name="academic")

MODERN_TEMPLATE = StyleTemplate(
    name="modern",
    heading1_font="微软雅黑",
    heading1_size=24,
    heading2_font="微软雅黑",
    heading2_size=18,
    heading3_font="微软雅黑",
    heading3_size=15,
    body_font="微软雅黑",
    body_size=12,
    body_line_spacing=1.75,
    body_first_line_indent=0,
)

TRAINING_TEMPLATE = StyleTemplate(
    name="training",
    heading1_size=26,
    heading2_size=20,
    body_size=14,
    body_line_spacing=2.0,
)

TEMPLATES = {
    "academic": ACADEMIC_TEMPLATE,
    "modern": MODERN_TEMPLATE,
    "training": TRAINING_TEMPLATE,
}

def get_template(name: str) -> StyleTemplate:
    return TEMPLATES.get(name, ACADEMIC_TEMPLATE)
