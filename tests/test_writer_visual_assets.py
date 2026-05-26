from agent.textbook.agents.writer import WriterAgent
from agent.textbook.pipeline.runner import PipelineRunner


def test_writer_parses_structured_visual_assets_before_markers():
    output = """
### PRE_WRITE_CHECK
ok

### VISUAL_ASSETS
```json
{
  "visual_assets": [
    {"type": "chart", "description": "Schedule comparison chart", "chart_type": "bar", "insert_after": "Progress control"},
    {"type": "image", "description": "Agent collaboration diagram", "image_type": "diagram", "insert_after": "System architecture"}
  ]
}
```

### CHAPTER_CONTENT
## Chapter text
This paragraph mentions [chart: Schedule comparison chart] and [image: Agent collaboration diagram].
"""

    parsed = WriterAgent()._parse_output(output, {"chapter_number": 1})

    assert parsed["chart_requirements"] == [
        {
            "description": "Schedule comparison chart",
            "chart_type": "bar",
            "insert_after": "Progress control",
        }
    ]
    assert parsed["image_requirements"] == [
        {
            "description": "Agent collaboration diagram",
            "image_type": "diagram",
            "insert_after": "System architecture",
        }
    ]


def test_pipeline_inserts_visual_asset_after_target_heading_when_marker_missing():
    content = "## Progress control\nBody\n## Next section\nMore"
    visual_requests = [
        {"description": "Schedule comparison chart", "insert_after": "Progress control"}
    ]

    result = PipelineRunner._insert_visual_assets(
        content,
        {"Schedule comparison chart": "assets/chart.png"},
        visual_requests,
    )

    image_marker = "![Schedule comparison chart](assets/chart.png)"
    assert image_marker in result
    assert result.index("## Progress control") < result.index(image_marker)
    assert result.index(image_marker) < result.index("## Next section")
