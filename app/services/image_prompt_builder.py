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
]

# 동화(FAIRY_TALE)는 삽화 특성상 인물이 여러 장에 걸쳐 반복 등장하고, 아동 독자 대상이라
# 이 조건들이 필요하다. 그 외 장르(소설/시/에세이 등)는 성인 독자도 많고 캐릭터가 없는
# 추상적인 표지도 흔해서, 이 조건을 붙이면 장르와 안 맞는 동화풍 삽화가 나온다.
FAIRY_TALE_IMAGE_CONDITIONS = [
    "consistent character design",
    "safe for children",
]


class ImagePromptBuildError(Exception):
    pass


def build_image_prompt(prompt_text: str, style: Optional[str], book_type: Optional[str] = None) -> str:
    """
    promptText + style 매핑 문구 + 공통 조건을 합쳐 이미지 생성 모델에 보낼 최종 영어 프롬프트를 만든다.

    Gemini 이미지 생성은 별도의 negative prompt 필드가 없어 "no text" 같은 금지 조건도
    프롬프트 본문에 그대로 녹여야 한다. 장면 묘사 뒤(맨 끝)에 붙이면 프롬프트가 길어질수록
    무시되거나 잘려나가기 쉬우므로, 안전/금지 조건을 장면 묘사보다 앞에 배치한다.
    """
    parts = []

    if style:
        style_phrase = STYLE_PROMPT_MAP.get(style)
        if not style_phrase:
            raise ImagePromptBuildError(f"지원하지 않는 style입니다: {style}")
        parts.append(style_phrase)

    parts.extend(COMMON_IMAGE_CONDITIONS)
    if book_type == "FAIRY_TALE":
        parts.extend(FAIRY_TALE_IMAGE_CONDITIONS)
    parts.append(prompt_text.strip())

    return ", ".join(parts)
