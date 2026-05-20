import sys
import json
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from agent.textbook.sandbox.image_prompt import ImagePromptEngineer, ImageGenerationRequest

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    description = args.get("description", "")
    image_type = args.get("image_type", "illustration")
    style = args.get("style", "professional")
    subject = args.get("subject", "")
    output_dir = args.get("output_dir", ".")
    image_size = args.get("image_size", "landscape_4_3")
    generate = args.get("generate", True)

    engineer = ImagePromptEngineer()

    request = ImageGenerationRequest(
        description=description,
        image_type=image_type,
        style=style,
        size=image_size,
        subject=subject
    )

    if generate:
        result = engineer.generate_and_save(request, output_dir)
        print(json.dumps(result, ensure_ascii=False))
    else:
        prompt = engineer.generate_prompt(request)
        url = engineer.generate_url(prompt, image_size)
        print(json.dumps({
            "status": "success",
            "prompt": prompt,
            "image_url": url
        }, ensure_ascii=False))

if __name__ == "__main__":
    main()
