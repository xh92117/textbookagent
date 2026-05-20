---
name: textbook-sandbox
description: Use when the user requests chart generation, code execution, data visualization, or knowledge graph creation. Sandboxed Python code execution with security controls.
triggers:
  - 生成图表
  - 画图
  - 折线图
  - 柱状图
  - 知识图谱
  - 执行代码
allowed-tools:
  - bash
  - read
  - write
---

# Sandbox Chart Generation

Execute Python code in a secure sandbox environment to generate charts for textbook content. Supports line, bar, pie, scatter, network graphs, and custom code. Subprocess isolation with dangerous module blocking and timeout control.

## 核心指令

1. **确定图表类型**: 根据用户需求或[图表:...]标记确定图表类型(line/bar/pie/scatter/network/custom)。
2. **准备数据**: 从上下文或用户输入中提取图表数据。
3. **选择执行方式**:
   - 标准图表 → 使用 `generate_chart.py` 脚本
   - 自定义代码 → 使用 `execute_sandbox.py` 脚本
4. **安全检查**: 确保代码不包含禁止导入的模块。
5. **执行并返回**: 执行代码，返回图表文件路径。

## 工作流示例

### 示例1：生成折线图
- **用户输入**: "画一个折线图，展示排序算法的时间复杂度对比"
- **模型思考**: 标准折线图，使用generate_chart.py。
- **模型行动**:
  1. 执行 `python <base_dir>/scripts/generate_chart.py '{"chart_type":"line","data":{"x":[100,500,1000,5000,10000],"y_series":{"冒泡排序":[1,25,100,2500,10000],"快速排序":[0.1,0.5,1,5,10]}},"title":"排序算法时间复杂度对比","xlabel":"数据量","ylabel":"耗时(ms)"}'`

### 示例2：执行自定义代码
- **用户输入**: "运行这段Python代码生成热力图"
- **模型行动**:
  1. 检查代码安全性（无禁止导入）
  2. 执行 `python <base_dir>/scripts/execute_sandbox.py '{"code":"...","timeout":30}'`

## Tool Usage Specification

- `bash`: Execute chart generation or sandbox scripts
  - Chart generation: `python <base_dir>/scripts/generate_chart.py '<json_args>'`
    - Parameters: `{"chart_type":"line|bar|pie|scatter|network|custom", "data":{...}, "title":"...", "filename":"..."}`
  - Sandbox execution: `python <base_dir>/scripts/execute_sandbox.py '<json_args>'`
    - Parameters: `{"code":"...", "timeout":30, "output_dir":"..."}`
- `read`: Read chart code templates
  - Line chart: `read("<base_dir>/templates/chart_line.py")`
  - Bar chart: `read("<base_dir>/templates/chart_bar.py")`
  - Network graph: `read("<base_dir>/templates/chart_network.py")`

## Output Specification

Report the following upon completion:
1. Chart type
2. Chart file path
3. Execution time
4. Error message (if any)

## Constraints

- Forbidden imports: os, subprocess, socket, shutil, sys, importlib
- Maximum timeout: 60 seconds
- Code executes in isolated subprocess — no access to main process filesystem
- Charts must be saved as files, not just displayed
- Network graph node limit: 100
- For textbook chapters, every `[图表:...]` marker should resolve to a saved asset path under `assets/charts/` and be inserted as Markdown.
- Prefer simple, readable chart data when source data is missing, and record the generated chart file path for Word export.
