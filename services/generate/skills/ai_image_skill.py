from __future__ import annotations

import base64
import io
import logging
import re

import httpx

from core.skill_engine.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

IMAGE_SIZES = {
    "landscape_16_9": "1792x1024",
    "landscape_4_3": "1024x768",
    "portrait_16_9": "1024x1792",
    "portrait_4_3": "768x1024",
    "square_hd": "1024x1024",
    "square": "512x512",
}

WATERMARK_PATTERNS = [
    re.compile(r'[\u00a9\u00ae\u2122]', re.IGNORECASE),
    re.compile(r'(watermark|水印|版权所有|copyright|all\s*rights\s*reserved)', re.IGNORECASE),
    re.compile(r'(getty\s*images|shutterstock|adobe\s*stock|istock|123rf|dreamstime)', re.IGNORECASE),
    re.compile(r'(visual\s*china|视觉中国|东方ic|全景视觉)', re.IGNORECASE),
]


class AiImageSkill(Skill):
    name = "ai_image"
    description = "AI配图生成，支持火山方舟/Google AI Studio，自动去水印"
    category = "generate"
    version = "2.0.0"
    triggers = ["配图", "生成图片", "AI配图", "插图"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        prompt = ctx.parameters.get("prompt", "")
        provider = ctx.parameters.get("provider", "fallback")
        image_size = ctx.parameters.get("image_size", "landscape_16_9")
        remove_watermark = ctx.parameters.get("remove_watermark", True)
        chapter_title = ctx.parameters.get("chapter_title", "")
        style_hint = ctx.parameters.get("style_hint", "professional,business,clean")

        if not prompt:
            return SkillResult(success=False, error="缺少图片描述prompt")

        enhanced_prompt = self._enhance_prompt(prompt, chapter_title, style_hint)

        try:
            if provider == "volcengine":
                result = await self._generate_volcengine(ctx, enhanced_prompt, image_size)
            elif provider == "google":
                result = await self._generate_google(ctx, enhanced_prompt, image_size)
            else:
                result = await self._generate_fallback(ctx, enhanced_prompt, image_size)
        except Exception as e:
            logger.warning(f"Provider {provider} failed, falling back: {e}")
            try:
                result = await self._generate_fallback(ctx, enhanced_prompt, image_size)
            except Exception as fallback_err:
                return SkillResult(
                    success=False,
                    error=f"所有图片生成服务均失败: {str(fallback_err)}",
                )

        if result.success and remove_watermark:
            result = await self._apply_watermark_removal(result)

        return result

    def _enhance_prompt(self, prompt: str, chapter_title: str, style_hint: str) -> str:
        parts = []
        if chapter_title:
            parts.append(f"Context: bidding document section about '{chapter_title}'")
        parts.append(prompt)
        parts.append(f"Style: {style_hint}")
        parts.append("No text overlay, no watermark, no logo, no copyright mark, clean professional image")
        return ". ".join(parts)

    async def _apply_watermark_removal(self, result: SkillResult) -> SkillResult:
        if not result.data:
            return result

        image_url = result.data.get("image_url", "")
        base64_data = result.data.get("base64", "")

        if not image_url and not base64_data:
            return result

        try:
            image_bytes = None
            if base64_data:
                image_bytes = base64.b64decode(base64_data)
            elif image_url:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(image_url)
                    if resp.status_code == 200:
                        image_bytes = resp.content

            if not image_bytes:
                return result

            cleaned = self._remove_watermark_from_bytes(image_bytes)
            if cleaned:
                result.data["base64"] = base64.b64encode(cleaned).decode("ascii")
                result.data["watermark_removed"] = True
                result.data["watermark_removal_method"] = "pillow_crop_inpaint"
            else:
                result.data["watermark_removed"] = False
                result.data["watermark_removal_method"] = "none_needed"

        except Exception as e:
            logger.warning(f"Watermark removal failed: {e}")
            result.data["watermark_removed"] = False
            result.data["watermark_removal_error"] = str(e)

        return result

    def _remove_watermark_from_bytes(self, image_bytes: bytes) -> bytes | None:
        try:
            from PIL import Image, ImageFilter
        except ImportError:
            logger.warning("Pillow not available, skipping watermark removal")
            return None

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            return None

        width, height = img.size
        has_watermark = False

        if img.mode in ("RGBA", "RGB", "L"):
            try:
                from pytesseract import image_to_string
                text = image_to_string(img).lower()
                for pattern in WATERMARK_PATTERNS:
                    if pattern.search(text):
                        has_watermark = True
                        break
            except Exception:
                pass

        if not has_watermark:
            bottom_region = img.crop((0, int(height * 0.85), width, height))
            try:
                from pytesseract import image_to_string
                bottom_text = image_to_string(bottom_region).lower()
                for pattern in WATERMARK_PATTERNS:
                    if pattern.search(bottom_text):
                        has_watermark = True
                        break
            except Exception:
                pass

        if not has_watermark:
            return None

        regions_to_clean = []

        corners = [
            (0, 0, int(width * 0.25), int(height * 0.08)),
            (int(width * 0.75), 0, width, int(height * 0.08)),
            (0, int(height * 0.92), int(width * 0.25), height),
            (int(width * 0.75), int(height * 0.92), width, height),
            (0, int(height * 0.85), width, height),
        ]

        for box in corners:
            x1, y1, x2, y2 = box
            if x2 > x1 and y2 > y1:
                region = img.crop(box)
                try:
                    from pytesseract import image_to_string
                    region_text = image_to_string(region).strip().lower()
                    if region_text:
                        for pattern in WATERMARK_PATTERNS:
                            if pattern.search(region_text):
                                regions_to_clean.append(box)
                                break
                except Exception:
                    pass

        if not regions_to_clean:
            regions_to_clean.append((0, int(height * 0.92), width, height))

        for box in regions_to_clean:
            x1, y1, x2, y2 = box
            if x2 <= x1 or y2 <= y1:
                continue

            region = img.crop(box)
            blurred = region.filter(ImageFilter.GaussianBlur(radius=8))

            for _ in range(3):
                blurred = blurred.filter(ImageFilter.GaussianBlur(radius=5))

            try:
                inpainted = Image.blend(region, blurred, alpha=0.85)
            except Exception:
                inpainted = blurred

            img.paste(inpainted, box)

        output = io.BytesIO()
        fmt = img.format or "PNG"
        if fmt.upper() == "JPEG":
            img = img.convert("RGB")
        img.save(output, format=fmt if fmt.upper() in ("PNG", "JPEG", "WEBP") else "PNG", quality=95)
        return output.getvalue()

    async def _generate_volcengine(
        self, ctx: SkillContext, prompt: str, image_size: str
    ) -> SkillResult:
        api_key = ctx.parameters.get("volcengine_api_key", "")
        if not api_key:
            api_key = ctx.parameters.get("api_key", "")
        if not api_key:
            return SkillResult(success=False, error="未配置火山方舟API Key")

        size_str = IMAGE_SIZES.get(image_size, "1792x1024")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://visual.volcengineapi.com/",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "req_key": "high_aes",
                    "prompt": prompt,
                    "width": int(size_str.split("x")[0]),
                    "height": int(size_str.split("x")[1]),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        image_url = ""
        if "data" in data and isinstance(data["data"], dict):
            image_url = data["data"].get("image_url", "") or data["data"].get("url", "")
        if not image_url and "image_url" in data:
            image_url = data["image_url"]

        return SkillResult(
            success=True,
            data={
                "image_url": image_url,
                "provider": "volcengine",
                "prompt": prompt,
                "image_size": image_size,
            },
        )

    async def _generate_google(
        self, ctx: SkillContext, prompt: str, image_size: str
    ) -> SkillResult:
        api_key = ctx.parameters.get("google_api_key", "")
        if not api_key:
            api_key = ctx.parameters.get("api_key", "")
        if not api_key:
            return SkillResult(success=False, error="未配置Google AI Studio API Key")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "instances": [{"prompt": prompt}],
                    "parameters": {
                        "sampleCount": 1,
                        "aspectRatio": self._get_aspect_ratio(image_size),
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()

        base64_data = ""
        if "predictions" in data and len(data["predictions"]) > 0:
            base64_data = data["predictions"][0].get("bytesBase64Encoded", "")

        return SkillResult(
            success=True,
            data={
                "base64": base64_data,
                "provider": "google",
                "prompt": prompt,
                "image_size": image_size,
            },
        )

    async def _generate_fallback(
        self, ctx: SkillContext, prompt: str, image_size: str
    ) -> SkillResult:
        encoded_prompt = base64.urlsafe_b64encode(prompt.encode("utf-8")).decode("ascii")
        url = f"https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt={encoded_prompt}&image_size={image_size}"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        image_url = ""
        base64_data = ""

        if isinstance(data, dict):
            image_url = data.get("image_url", "") or data.get("url", "")
            base64_data = data.get("base64", "") or data.get("image", "")
            if not image_url and not base64_data:
                if "data" in data and isinstance(data["data"], dict):
                    image_url = data["data"].get("image_url", "") or data["data"].get("url", "")
                    base64_data = data["data"].get("base64", "") or data["data"].get("image", "")

        return SkillResult(
            success=True,
            data={
                "image_url": image_url,
                "base64": base64_data,
                "provider": "fallback",
                "prompt": prompt,
                "image_size": image_size,
            },
        )

    @staticmethod
    def _get_aspect_ratio(image_size: str) -> str:
        mapping = {
            "landscape_16_9": "16:9",
            "landscape_4_3": "4:3",
            "portrait_16_9": "9:16",
            "portrait_4_3": "3:4",
            "square_hd": "1:1",
            "square": "1:1",
        }
        return mapping.get(image_size, "16:9")
