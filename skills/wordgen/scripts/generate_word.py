import sys
import json
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from agent.textbook.docgen.word_generator import MarkdownToWordConverter
from agent.textbook.docgen.style_template import get_template, StyleTemplate
from agent.textbook.state.truth_files import TruthFileManager

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    book_id = args.get("book_id", "")
    template_name = args.get("template", "academic")
    chapter_numbers = args.get("chapters", None)
    output_dir = args.get("output_dir", ".")
    book_dir = args.get("book_dir", "")

    if not book_dir:
        print(json.dumps({"status": "error", "message": "book_dir is required"}, ensure_ascii=False))
        return

    template = get_template(template_name)
    converter = MarkdownToWordConverter(template)

    truth_mgr = TruthFileManager(book_dir)

    outline_content = truth_mgr.read("outline")
    converter.convert_markdown(outline_content)

    if chapter_numbers:
        chapters_to_export = chapter_numbers
    else:
        all_chapters = truth_mgr.list_chapters()
        chapters_to_export = [c.get("num", i+1) for i, c in enumerate(all_chapters)] if all_chapters else list(range(1, 20))

    for num in chapters_to_export:
        try:
            chapter_content = truth_mgr.read_chapter(int(num))
            if chapter_content:
                converter.convert_markdown(chapter_content)
        except Exception:
            pass

    os.makedirs(output_dir, exist_ok=True)
    title = args.get("title", "textbook")
    filename = args.get("filename", f"{title}.docx")
    output_path = os.path.join(output_dir, filename)
    converter.save(output_path)

    print(json.dumps({
        "status": "success",
        "output_path": output_path,
        "template": template_name,
        "chapters_exported": len(chapters_to_export) if chapter_numbers else "all"
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
