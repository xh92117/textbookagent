import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent.textbook.sandbox.executor import SandboxExecutor, SandboxResult
from agent.textbook.sandbox.chart_generator import ChartGenerator
from agent.textbook.sandbox.image_prompt import ImagePromptEngineer, ImageGenerationRequest


def test_sandbox_simple_execution():
    executor = SandboxExecutor()
    result = executor.execute("print(1 + 1)")
    assert result.success is True, f"执行应成功，但 stderr={result.stderr}"
    assert "2" in result.stdout, f"输出应包含 2，实际为 {result.stdout}"
    assert result.exit_code == 0


def test_sandbox_forbidden_import():
    executor = SandboxExecutor()
    result = executor.execute("import os\nprint('hello')")
    assert result.success is False, "含禁止导入的代码应执行失败"
    assert "forbidden" in result.stderr.lower(), f"stderr 应提及 forbidden，实际为 {result.stderr}"


def test_sandbox_rejects_dynamic_import_escape():
    executor = SandboxExecutor()
    result = executor.execute("__import__('os').listdir('.')")
    assert result.success is False
    assert "forbidden call" in result.stderr.lower()


def test_sandbox_rejects_direct_file_read():
    executor = SandboxExecutor()
    result = executor.execute("open('anything.txt').read()")
    assert result.success is False
    assert "forbidden call" in result.stderr.lower()


def test_sandbox_timeout():
    executor = SandboxExecutor()
    result = executor.execute("import time\ntime.sleep(60)", timeout=2)
    assert result.success is False, "超时执行应失败"
    assert "timed out" in result.stderr.lower(), f"stderr 应提及超时，实际为 {result.stderr}"
    assert result.exit_code == -1


def test_sandbox_output_file():
    tmp_dir = tempfile.mkdtemp(prefix="sandbox_test_")
    executor = SandboxExecutor(output_dir=tmp_dir)
    code = """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.plot([1, 2, 3], [4, 5, 6])
plt.savefig('test_output.png', dpi=100)
plt.close()
"""
    result = executor.execute(code)
    assert result.success is True, f"matplotlib 代码应执行成功，stderr={result.stderr}"
    assert len(result.output_files) > 0, "应生成输出文件"


def test_chart_line():
    tmp_dir = tempfile.mkdtemp(prefix="sandbox_chart_")
    executor = SandboxExecutor(output_dir=tmp_dir)
    chart = ChartGenerator(executor=executor)
    result = chart.generate_line_chart(
        x_data="[1, 2, 3, 4, 5]",
        y_data="[10, 20, 15, 25, 30]",
        title="测试折线图",
        xlabel="X轴",
        ylabel="Y轴",
        filename="test_line.png",
    )
    assert result.success is True, f"折线图生成应成功，stderr={result.stderr}"


def test_chart_bar():
    tmp_dir = tempfile.mkdtemp(prefix="sandbox_chart_")
    executor = SandboxExecutor(output_dir=tmp_dir)
    chart = ChartGenerator(executor=executor)
    result = chart.generate_bar_chart(
        categories="['A', 'B', 'C']",
        values="[10, 20, 15]",
        title="测试柱状图",
        xlabel="类别",
        ylabel="数值",
        filename="test_bar.png",
    )
    assert result.success is True, f"柱状图生成应成功，stderr={result.stderr}"


def test_image_prompt():
    engineer = ImagePromptEngineer()
    request = ImageGenerationRequest(
        description="函数极限示意图",
        image_type="diagram",
        style="professional",
    )
    prompt = engineer.generate_prompt(request)
    assert "函数极限示意图" in prompt, f"提示词应包含描述，实际为 {prompt}"
    assert "professional" in prompt.lower() or "clean" in prompt.lower(), f"提示词应包含风格关键词，实际为 {prompt}"
    assert "diagram" in prompt.lower(), f"提示词应包含类型关键词，实际为 {prompt}"


def test_image_prompt_url():
    engineer = ImagePromptEngineer()
    request = ImageGenerationRequest(
        description="微积分基本定理图示",
        image_type="illustration",
        style="detailed",
        size="landscape_16_9",
    )
    url = engineer.generate_url("https://api.example.com/generate", request)
    assert url.startswith("https://api.example.com/generate?"), f"URL 格式不正确: {url}"
    assert "prompt=" in url, f"URL 应包含 prompt 参数: {url}"
    assert "image_size=landscape_16_9" in url, f"URL 应包含 image_size 参数: {url}"
