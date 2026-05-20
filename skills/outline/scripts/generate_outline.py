import sys
import json
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from agent.textbook.agents.outliner import OutlinerAgent
from agent.textbook.models.textbook import TextbookConfig

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

    config = TextbookConfig(
        title=args.get("title", ""),
        subject=args.get("subject", ""),
        target_audience=args.get("target_audience", ""),
        level=args.get("level", ""),
        total_chapters=args.get("total_chapters", 10),
        style=args.get("style", "学术"),
        curriculum_standard=args.get("curriculum_standard", ""),
    )
    if args.get("book_id"):
        config.id = args["book_id"]

    input_data = {
        "title": config.title,
        "subject": config.subject,
        "target_audience": config.target_audience,
        "level": config.level,
        "total_chapters": config.total_chapters,
        "chapter_word_count": args.get("chapter_word_count", 5000),
        "style": config.style,
        "curriculum_standard": config.curriculum_standard,
        "requirement": args.get("requirement", ""),
    }

    agent = OutlinerAgent()
    result = agent.run_standalone(input_data)

    output_dir = args.get("output_dir", ".")
    os.makedirs(output_dir, exist_ok=True)

    outline_path = os.path.join(output_dir, "outline.md")
    outline_content = result.get("outline_text", result.get("raw_output", ""))

    with open(outline_path, "w", encoding="utf-8") as f:
        f.write(outline_content)

    output = {
        "status": "success",
        "outline_path": outline_path,
        "book_id": config.id,
        "title": config.title,
        "total_chapters": config.total_chapters,
    }

    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
