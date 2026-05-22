from agent.textbook.metrics import measure_content


def test_measure_content_excludes_scaffolding_code_and_visual_markers():
    content = """### PRE_WRITE_CHECK
| 检查项 | 状态 |
|---|---|
| 章节目标覆盖 | 是 |

### VISUAL_ASSETS
```json
{"visual_assets": [{"type": "chart", "description": "流程图"}]}
```

### CHAPTER_CONTENT
## 第一章

这是正文内容，用于统计有效字数。

```python
print("这段代码不计入正文有效字数")
```

[图表: 教学流程图]
"""

    metrics = measure_content(content)

    assert metrics.content_chars > metrics.effective_chars
    assert metrics.visual_markers == 1
    assert metrics.code_lines > 0
    assert "代码" not in str(metrics.effective_word_count)
    assert metrics.effective_word_count < metrics.content_chars
    assert metrics.cjk_chars >= len("这是正文内容用于统计有效字数")
