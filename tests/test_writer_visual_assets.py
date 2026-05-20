from agent.textbook.agents.writer import WriterAgent


def test_writer_parses_structured_visual_assets_before_markers():
    output = """
### PRE_WRITE_CHECK
ok

### VISUAL_ASSETS
```json
{
  "visual_assets": [
    {"type": "chart", "description": "施工进度对比图", "chart_type": "bar", "insert_after": "进度控制"},
    {"type": "image", "description": "智能体协作架构图", "image_type": "diagram", "insert_after": "系统架构"}
  ]
}
```

### CHAPTER_CONTENT
## 第1章
这里需要[图表: 施工进度对比图]，也需要[插图: 智能体协作架构图]。
"""

    parsed = WriterAgent()._parse_output(output, {"chapter_number": 1})

    assert parsed["chart_requirements"] == [
        {
            "description": "施工进度对比图",
            "chart_type": "bar",
            "insert_after": "进度控制",
        }
    ]
    assert parsed["image_requirements"] == [
        {
            "description": "智能体协作架构图",
            "image_type": "diagram",
            "insert_after": "系统架构",
        }
    ]
