import sys
import json
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from agent.textbook.sandbox.executor import SandboxExecutor

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    code = args.get("code", "")
    timeout = args.get("timeout", 30)
    output_dir = args.get("output_dir", "")

    executor = SandboxExecutor(timeout=timeout, output_dir=output_dir)
    result = executor.execute(code)

    print(json.dumps({
        "status": "success" if result.success else "error",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "output_files": result.output_files,
        "execution_time": result.execution_time
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
