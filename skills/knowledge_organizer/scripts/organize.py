import sys
import json
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from agent.knowledge.service import KnowledgeService


def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    book_id = args.get("book_id", "")
    action = args.get("action", "organize")

    from common.utils import expand_path
    from config import conf
    workspace_root = expand_path(conf().get("agent_workspace", "~/textbook_workspace"))
    service = KnowledgeService(workspace_root)

    if action == "organize":
        result = service.organize_knowledge(book_id)
        print(json.dumps(result, ensure_ascii=False))
    elif action == "graph":
        result = service.get_knowledge_graph(book_id)
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"status": "error", "message": f"unknown action: {action}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
