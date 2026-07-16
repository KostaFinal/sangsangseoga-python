# app/services/gemini_image_service.py

import asyncio
import base64
import os
from typing import Optional, Tuple

from google.genai import errors as genai_errors
from google.genai import types

from app.services.gemini_service import (
    MAX_RETRIES,
    RETRY_BACKOFF_SECONDS,
    RETRYABLE_STATUS_CODES,
    client,
)


GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


class GeminiImageServiceError(Exception):
    pass


async def _generate_content_with_retry(prompt: str, aspect_ratio: str):
    last_error: Optional[Exception] = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return await client.aio.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                ),
            )
        except genai_errors.APIError as e:
            last_error = e
            if getattr(e, "code", None) in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise

    raise last_error


async def generate_image(prompt: str, aspect_ratio: str = "3:4") -> Tuple[str, str]:
    """
    Gemini 2.5 Flash Image로 이미지를 생성해 (base64 데이터, mime_type)을 반환한다.
    Replicate와 달리 호스팅된 URL이 아니라 이미지 바이트를 응답에 바로 담아서 준다.
    """
    try:
        response = await _generate_content_with_retry(prompt, aspect_ratio)
    except Exception as e:
        raise GeminiImageServiceError(f"Gemini 이미지 생성 중 오류가 발생했습니다: {str(e)}")

    candidates = response.candidates or []
    parts = candidates[0].content.parts if candidates and candidates[0].content else []

    for part in parts:
        if part.inline_data and part.inline_data.data:
            image_base64 = base64.b64encode(part.inline_data.data).decode("ascii")
            mime_type = part.inline_data.mime_type or "image/png"
            return image_base64, mime_type

    raise GeminiImageServiceError("Gemini 응답에서 이미지 데이터를 찾지 못했습니다.")
