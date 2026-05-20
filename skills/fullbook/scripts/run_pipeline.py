import sys
import json
import os
import threading
import asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from agent.textbook.pipeline.runner import PipelineRunner
from agent.textbook.models.textbook import TextbookConfig

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

    config = TextbookConfig(
        title=args.get("title", ""),
        subject=args.get("subject", ""),
        target_audience=args.get("target_audience", ""),
        level=args.get("level", ""),
        total_chapters=args.get("total_chapters", 10),
        chapter_word_count=args.get("chapter_word_count", 5000),
        style=args.get("style", "学术"),
        curriculum_standard=args.get("curriculum_standard", ""),
    )
    if args.get("book_id"):
        config.id = args["book_id"]

    events = []
    def on_event(event):
        events.append(event)

    runner = PipelineRunner(on_event=on_event)

    requirement = args.get("requirement", "")

    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(runner.run_full_pipeline(config, requirement))
    loop.close()

    output_dir = args.get("output_dir", ".")
    os.makedirs(output_dir, exist_ok=True)

    result_path = os.path.join(output_dir, "pipeline_result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "status": "success",
        "result_path": result_path,
        "book_id": config.id,
        "phases_completed": len([e for e in events if e.get("type") == "phase_complete"]),
        "total_events": len(events)
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
