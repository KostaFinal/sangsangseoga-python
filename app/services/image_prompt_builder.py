# app/services/image_prompt_builder.py

from typing import Optional


STYLE_PROMPT_MAP = {
    "PASTEL": "warm pastel children's book illustration",
    "WATERCOLOR": "soft watercolor children's book illustration",
    "CUTE_3D": "cute 3D storybook style",
    "PICTURE_BOOK": "classic children's picture book illustration",
}


COMMON_IMAGE_CONDITIONS = [
    "vertical 3:4 composition",
    "no text",
    "no letters",
    "no speech bubbles",
    "consistent character design",
    "safe for children",
]


class ImagePromptBuildError(Exception):
    pass


def build_image_prompt(prompt_text: str, style: Optional[str]) -> str:
    """
    promptText + style 매핑 문구 + 공통 조건을 합쳐 Replicate에 보낼 최종 영어 프롬프트를 만든다.

    flux-schnell은 negative prompt를 지원하지 않아 "no text" 같은 금지 조건도 프롬프트
    본문에 그대로 녹여야 한다. 장면 묘사 뒤(맨 끝)에 붙이면 프롬프트가 길어질수록
    무시되거나 잘려나가기 쉬우므로, 안전/금지 조건을 장면 묘사보다 앞에 배치한다.
    """
    parts = []

    if style:
        style_phrase = STYLE_PROMPT_MAP.get(style)
        if not style_phrase:
            raise ImagePromptBuildError(f"지원하지 않는 style입니다: {style}")
        parts.append(style_phrase)

    parts.extend(COMMON_IMAGE_CONDITIONS)
    parts.append(prompt_text.strip())

    return ", ".join(parts)
