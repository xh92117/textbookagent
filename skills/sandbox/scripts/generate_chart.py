import sys
import json
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from agent.textbook.sandbox.chart_generator import ChartGenerator
from agent.textbook.sandbox.executor import SandboxExecutor

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    chart_type = args.get("chart_type", "line")
    data = args.get("data", {})
    filename = args.get("filename", "")
    output_dir = args.get("output_dir", ".")

    executor = SandboxExecutor(output_dir=output_dir)
    generator = ChartGenerator(executor=executor)

    if chart_type == "line":
        result = generator.generate_line_chart(
            data.get("x", []),
            data.get("y_series", {}),
            title=data.get("title", ""),
            xlabel=data.get("xlabel", ""),
            ylabel=data.get("ylabel", ""),
            filename=filename
        )
    elif chart_type == "bar":
        result = generator.generate_bar_chart(
            data.get("categories", []),
            data.get("values", {}),
            title=data.get("title", ""),
            xlabel=data.get("xlabel", ""),
            ylabel=data.get("ylabel", ""),
            filename=filename
        )
    elif chart_type == "pie":
        result = generator.generate_pie_chart(
            data.get("labels", []),
            data.get("sizes", []),
            title=data.get("title", ""),
            filename=filename
        )
    elif chart_type == "scatter":
        result = generator.generate_scatter_chart(
            data.get("x", []),
            data.get("y", []),
            title=data.get("title", ""),
            xlabel=data.get("xlabel", ""),
            ylabel=data.get("ylabel", ""),
            filename=filename
        )
    elif chart_type == "network":
        result = generator.generate_network_graph(
            data.get("nodes", []),
            data.get("edges", []),
            title=data.get("title", ""),
            filename=filename
        )
    elif chart_type == "custom":
        code = args.get("code", "")
        result = generator.execute_custom(code, filename=filename)
    else:
        print(json.dumps({"status": "error", "message": f"Unsupported chart type: {chart_type}"}, ensure_ascii=False))
        return

    print(json.dumps({
        "status": "success",
        "chart_type": chart_type,
        "result": result
    }, ensure_ascii=False, default=str))

if __name__ == "__main__":
    main()
