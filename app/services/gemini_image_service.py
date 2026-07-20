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


def _build_contents(prompt: str, reference_image_bytes: Optional[bytes], reference_image_mime_type: Optional[str]):
    # 레퍼런스 이미지가 있으면 이미지+텍스트를 함께 넣어 Gemini가 그 이미지를 참고해서 그리도록 한다
    # (캐릭터 일관성용 - 표지 이미지를 이후 페이지 생성에 레퍼런스로 넣는 용도).
    # 레퍼런스가 없으면(표지 자체를 만들 때 등) 지금까지와 동일하게 텍스트만 보낸다.
    if reference_image_bytes:
        return [
            types.Part.from_bytes(data=reference_image_bytes, mime_type=reference_image_mime_type or "image/png"),
            prompt,
        ]
    return prompt


async def _generate_content_with_retry(
    prompt: str,
    aspect_ratio: str,
    reference_image_bytes: Optional[bytes] = None,
    reference_image_mime_type: Optional[str] = None,
):
    last_error: Optional[Exception] = None
    contents = _build_contents(prompt, reference_image_bytes, reference_image_mime_type)

    for attempt in range(MAX_RETRIES + 1):
        try:
            return await client.aio.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=contents,
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


async def generate_image(
    prompt: str,
    aspect_ratio: str = "3:4",
    reference_image_base64: Optional[str] = None,
    reference_image_mime_type: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Gemini 2.5 Flash Image로 이미지를 생성해 (base64 데이터, mime_type)을 반환한다.
    Replicate와 달리 호스팅된 URL이 아니라 이미지 바이트를 응답에 바로 담아서 준다.
    reference_image_base64가 있으면(예: 표지 이미지) 그 이미지를 함께 입력으로 넣어
    캐릭터 외형을 그 이미지에 맞춰 그리도록 유도한다.
    """
    reference_image_bytes = base64.b64decode(reference_image_base64) if reference_image_base64 else None

    try:
        response = await _generate_content_with_retry(
            prompt, aspect_ratio, reference_image_bytes, reference_image_mime_type
        )
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
