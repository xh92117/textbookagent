from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote
import base64
import json
import os
import time
import urllib.request


@dataclass
class ImageGenerationRequest:
    description: str = ""
    image_type: str = "diagram"
    style: str = "professional"
    size: str = "landscape_4_3"
    language: str = "zh"
    subject: str = ""


class ImagePromptEngineer:
    STYLE_KEYWORDS = {
        "professional": "clean, professional, textbook illustration, clear labels, high contrast, educational",
        "minimal": "minimal, simple, flat design, limited colors, clear lines",
        "detailed": "detailed, realistic, annotated, comprehensive, technical drawing",
    }

    IMAGE_TYPE_KEYWORDS = {
        "diagram": "diagram, flowchart, schematic, technical illustration",
        "illustration": "illustration, visual explanation, concept art",
        "screenshot": "screenshot, interface, software UI, application window",
        "photo": "photograph, real-world, physical object, scene",
    }

    SIZE_MAP = {
        "square_hd": "1024*1024",
        "square": "1024*1024",
        "portrait_4_3": "960*1280",
        "portrait_16_9": "720*1280",
        "landscape_4_3": "1280*960",
        "landscape_16_9": "1280*720",
    }
    LEGACY_SIZE_MAP = {
        "square_hd": "square_hd",
        "square": "square",
        "portrait_4_3": "portrait_4_3",
        "portrait_16_9": "portrait_16_9",
        "landscape_4_3": "landscape_4_3",
        "landscape_16_9": "landscape_16_9",
    }

    def generate_prompt(self, request: ImageGenerationRequest) -> str:
        style_kw = self.STYLE_KEYWORDS.get(request.style, self.STYLE_KEYWORDS["professional"])
        type_kw = self.IMAGE_TYPE_KEYWORDS.get(request.image_type, self.IMAGE_TYPE_KEYWORDS["diagram"])

        prompt = (
            f"{request.description}, {type_kw}, {style_kw}, flat vector infographic, "
            "white background, clear visual hierarchy, large readable shapes, suitable for printing, "
            "CMYK-friendly colors, no watermark, no embedded text, no text overlay, no fake labels"
        )

        if request.language == "zh":
            prompt += ", use numbered callout circles only if annotations are needed"

        if request.subject:
            prompt += f", {request.subject} related"

        return prompt

    def generate_url(self, prompt_or_base_url: str, image_size: str = "landscape_4_3") -> str:
        if isinstance(image_size, ImageGenerationRequest):
            request = image_size
            base_url = prompt_or_base_url
            prompt = self.generate_prompt(request)
            image_size = self.LEGACY_SIZE_MAP.get(request.size, "landscape_4_3")
        else:
            prompt = prompt_or_base_url
            base_url = os.environ.get('IMAGE_GEN_BASE_URL', 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image')
        encoded_prompt = quote(prompt)
        return f"{base_url}?prompt={encoded_prompt}&image_size={image_size}"

    def generate_and_save(self, request: ImageGenerationRequest, output_dir: str, filename: str = None) -> dict:
        prompt = self.generate_prompt(request)

        if not filename:
            filename = f"img_{int(time.time())}.png"

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, filename)

        configured = self._generate_with_configured_model(request, prompt, output_path)
        if configured.get("attempted"):
            return configured

        image_size = self.LEGACY_SIZE_MAP.get(request.size, "landscape_4_3")
        url = self.generate_url(prompt, image_size)

        try:
            urllib.request.urlretrieve(url, output_path)
            if self._looks_like_pending_placeholder(output_path):
                return {
                    "status": "error",
                    "prompt": prompt,
                    "error": "legacy image endpoint returned a pending placeholder instead of final artwork",
                    "image_url": url
                }
            return {
                "status": "success",
                "prompt": prompt,
                "image_path": output_path,
                "image_url": url,
                "filename": filename
            }
        except Exception as e:
            return {
                "status": "error",
                "prompt": prompt,
                "error": str(e),
                "image_url": url
            }

    def _generate_with_configured_model(self, request: ImageGenerationRequest, prompt: str, output_path: str) -> dict:
        cfg = self._resolve_image_model_config()
        if not cfg.get("model") or not cfg.get("api_key"):
            return {"attempted": False}
        provider = (cfg.get("provider") or "").lower()
        model = cfg.get("model", "")
        if provider not in ("dashscope", "custom", "qianwen", "tongyi", "openai", "chatgpt") and not any(x in model.lower() for x in ("qwen", "wan", "image", "dall-e")):
            return {"attempted": False}

        try:
            image_url, raw = "", {}
            try:
                image_url, raw = self._call_openai_compatible_image_generation(
                    model=model,
                    api_key=cfg["api_key"],
                    api_base=cfg.get("api_base", ""),
                    prompt=prompt,
                    size=self._image_api_size(provider, model, request.size),
                    output_path=output_path,
                )
            except Exception as first_error:
                raw = {"openai_compatible_error": str(first_error)}
            api_base = cfg.get("api_base", "")
            if not image_url and not os.path.exists(output_path) and "coding.dashscope.aliyuncs.com" not in api_base:
                image_url, raw = self._call_dashscope_multimodal_generation(
                    model=model,
                    api_key=cfg["api_key"],
                    api_base=api_base,
                    prompt=prompt,
                    size=self.SIZE_MAP.get(request.size, "1280*960"),
                )
            if not image_url and not os.path.exists(output_path):
                return {
                    "attempted": True,
                    "status": "error",
                    "prompt": prompt,
                    "error": f"configured image model returned no image url: {str(raw)[:500]}",
                }
            if image_url and not os.path.exists(output_path):
                self._download_image(image_url, output_path)
            if self._looks_like_pending_placeholder(output_path):
                return {
                    "attempted": True,
                    "status": "error",
                    "prompt": prompt,
                    "error": "configured image model returned a pending placeholder instead of final artwork",
                    "image_url": image_url,
                    "model": model,
                }
            return {
                "attempted": True,
                "status": "success",
                "prompt": prompt,
                "image_path": output_path,
                "image_url": image_url,
                "filename": os.path.basename(output_path),
                "model": model,
                "provider": provider or "dashscope",
            }
        except Exception as e:
            return {
                "attempted": True,
                "status": "error",
                "prompt": prompt,
                "error": str(e),
                "model": model,
                "provider": provider or "dashscope",
            }

    def _resolve_image_model_config(self) -> dict:
        try:
            from config import conf
            c = conf()
        except Exception:
            return {}

        model_id = c.get("image_model_id", "")
        selected = None
        for item in c.get("ai_chat_models", []) or []:
            if item.get("id") == model_id:
                selected = item
                break

        provider = (selected or {}).get("provider") or c.get("image_bot_type") or c.get("bot_type", "")
        model = (selected or {}).get("model") or c.get("image_model") or c.get("model", "")
        api_base = (selected or {}).get("api_base") or c.get("image_api_base") or c.get(f"{provider}_api_base", "")

        api_key = (selected or {}).get("api_key") or c.get("image_api_key", "")
        provider_key_map = {
            "dashscope": "dashscope_api_key",
            "deepseek": "deepseek_api_key",
            "custom": "custom_api_key",
            "zhipu": "zhipu_ai_api_key",
            "qianfan": "qianfan_api_key",
            "moonshot": "moonshot_api_key",
            "doubao": "ark_api_key",
        }
        api_key = api_key or c.get(provider_key_map.get(provider, ""), "") or c.get("dashscope_api_key", "") or c.get("custom_api_key", "")
        api_base = api_base or c.get("dashscope_api_base", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        return {
            "provider": provider,
            "model": model,
            "api_key": api_key,
            "api_base": api_base,
        }

    def _image_api_size(self, provider: str, model: str, size_key: str) -> str:
        model_lower = (model or "").lower()
        if provider in ("openai", "chatgpt") or model_lower.startswith(("gpt-image", "dall-e")):
            if size_key in ("landscape_4_3", "landscape_16_9"):
                return "1536x1024"
            if size_key in ("portrait_4_3", "portrait_16_9"):
                return "1024x1536"
            return "1024x1024"
        return self.SIZE_MAP.get(size_key, "1280*960")

    def _dashscope_generation_endpoint(self, api_base: str) -> str:
        base = (api_base or "").rstrip("/")
        if "dashscope-intl" in base:
            return "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        if "/api/v1" in base:
            return base.split("/api/v1")[0] + "/api/v1/services/aigc/multimodal-generation/generation"
        return "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

    def _call_dashscope_multimodal_generation(self, model: str, api_key: str, api_base: str, prompt: str, size: str) -> tuple:
        url = self._dashscope_generation_endpoint(api_base)
        payload = {
            "model": model,
            "input": {
                "messages": [
                    {"role": "user", "content": [{"text": prompt}]}
                ]
            },
            "parameters": {
                "size": size,
                "watermark": False,
                "prompt_extend": True,
                "negative_prompt": "low quality, blurry, distorted text, unreadable labels, cluttered layout, watermark",
            },
        }
        data = self._post_json(url, api_key, payload)
        image_url = self._extract_image_url(data)
        if image_url:
            return image_url, data

        task_id = (data.get("output") or {}).get("task_id")
        if task_id:
            task_data = self._poll_dashscope_task(api_base, api_key, task_id)
            return self._extract_image_url(task_data), task_data
        return "", data

    def _call_openai_compatible_image_generation(
        self,
        model: str,
        api_key: str,
        api_base: str,
        prompt: str,
        size: str,
        output_path: str,
    ) -> tuple:
        base = (api_base or "https://api.openai.com/v1").rstrip("/")
        if not base.endswith("/v1"):
            base = base + "/v1"
        url = f"{base}/images/generations"
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "n": 1,
        }
        data = self._post_json(url, api_key, payload)
        items = data.get("data") or []
        if not items:
            return "", data
        first = items[0]
        if first.get("url"):
            return first["url"], data
        if first.get("b64_json"):
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(first["b64_json"]))
            return "b64_json", data
        return "", data

    def _post_json(self, url: str, api_key: str, payload: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(f"HTTP {e.code} {e.reason}: {body[:1000]}") from e

    def _poll_dashscope_task(self, api_base: str, api_key: str, task_id: str) -> dict:
        host = "https://dashscope-intl.aliyuncs.com" if "dashscope-intl" in (api_base or "") else "https://dashscope.aliyuncs.com"
        url = f"{host}/api/v1/tasks/{task_id}"
        last_data = {}
        for _ in range(36):
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"}, method="GET")
            with urllib.request.urlopen(req, timeout=60) as resp:
                last_data = json.loads(resp.read().decode("utf-8"))
            status = (last_data.get("output") or {}).get("task_status")
            if status == "SUCCEEDED":
                return last_data
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                raise RuntimeError(f"DashScope image task {status}: {last_data}")
            time.sleep(5)
        raise TimeoutError(f"DashScope image task timed out: {task_id}, last={last_data}")

    def _extract_image_url(self, data: dict) -> str:
        output = data.get("output") or {}
        for key in ("image_url", "url"):
            if output.get(key):
                return output[key]
        results = output.get("results") or []
        for item in results:
            if item.get("url"):
                return item["url"]
            if item.get("image"):
                return item["image"]
        choices = output.get("choices") or []
        for choice in choices:
            content = ((choice.get("message") or {}).get("content")) or []
            for item in content:
                if item.get("image"):
                    return item["image"]
                if item.get("image_url"):
                    return item["image_url"]
        return ""

    def _download_image(self, image_url: str, output_path: str):
        req = urllib.request.Request(image_url, headers={"User-Agent": "TextBookAgent/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()
        if content_type and "image" not in content_type.lower():
            raise RuntimeError(f"image url returned non-image content type: {content_type}")
        with open(output_path, "wb") as f:
            f.write(data)

    def _looks_like_pending_placeholder(self, image_path: str) -> bool:
        try:
            from PIL import Image
            img = Image.open(image_path).convert("L").resize((64, 64))
            stat = img.getextrema()
            if stat[1] - stat[0] < 35:
                return True
            width, height = Image.open(image_path).size
            return (width, height) == (1832, 1832) and os.path.getsize(image_path) < 220000
        except Exception:
            return False

    def generate_prompts_for_chapter(self, image_requirements: list) -> list:
        results = []
        for req in image_requirements:
            img_req = ImageGenerationRequest(
                description=req.get('description', ''),
                image_type=req.get('image_type', 'diagram'),
                style='professional',
                size=req.get('size', 'landscape_4_3'),
            )
            results.append(self.generate_prompt(img_req))
        return results
