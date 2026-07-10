# app/services/prompt_builder.py

import json
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[2]
PROMPTS_DIR = BASE_DIR / "prompts"


READER_AGE_FILE_MAP = {
    "PRESCHOOL": "preschool.txt",
    "LOWER_ELEMENTARY": "lower_elementary.txt",
    "UPPER_ELEMENTARY": "upper_elementary.txt",
    "TEEN": "teen.txt",
    "ADULT": "adult.txt",
}


BOOK_TYPE_GENRE_FILE_MAP = {
    "FAIRY_TALE": "fairy_tale.txt",
    "NOVEL": "novel.txt",
}


INTERACTION_MODE_FILE_MAP = {
    "FREE": "free.txt",
    "MIXED": "mixed.txt",
    "CHOICE": "choice.txt",
}


TASK_FILE_MAP = {
    # 공통 task
    "COLLECT_SETTING": "task/common/collect_setting.txt",
    "NORMALIZE_SETTING": "task/common/normalize_setting.txt",
    "CREATE_SETTING_OPTIONS": "task/common/create_setting_options.txt",
    "TRANSLATE_TEXT": "task/common/translate_text.txt",

    # 동화 task
    "CREATE_PAGE_PLAN": "task/fairy_tale/create_page_plan.txt",
    "WRITE_PAGE": "task/fairy_tale/write_page.txt",
    "REWRITE_PAGE": "task/fairy_tale/rewrite_page.txt",
    "CREATE_IMAGE_PROMPT": "task/fairy_tale/create_image_prompt.txt",

    # 소설 task
    "CREATE_SCENE_PLAN": "task/novel/create_scene_plan.txt",
    "WRITE_SCENE": "task/novel/write_scene.txt",
    "REWRITE_SCENE": "task/novel/rewrite_scene.txt",
    "CREATE_COVER_PROMPT": "task/novel/create_cover_prompt.txt",
}


class PromptBuildError(Exception):
    pass


def read_prompt_file(relative_path: str) -> str:
    file_path = PROMPTS_DIR / relative_path

    if not file_path.exists():
        raise PromptBuildError(f"프롬프트 파일을 찾을 수 없습니다: {file_path}")

    return file_path.read_text(encoding="utf-8").strip()


def build_prompt(request_data: Dict[str, Any]) -> str:
    task_type = request_data.get("taskType")
    draft = request_data.get("draft", {})
    book_type = draft.get("bookType")
    meta = draft.get("meta", {})

    reader_age = meta.get("readerAge")
    interaction_mode = meta.get("interactionMode")

    prompt_paths: List[str] = []

    # 1. 항상 들어가는 공통 프롬프트
    prompt_paths.append("common/safety.txt")
    prompt_paths.append("common/json_rule.txt")

    # 2. 독자 나이별 프롬프트
    if reader_age:
        reader_age_file = READER_AGE_FILE_MAP.get(reader_age)
        if not reader_age_file:
            raise PromptBuildError(f"지원하지 않는 readerAge입니다: {reader_age}")

        prompt_paths.append(f"reader_age/{reader_age_file}")

    # 3. 장르별 프롬프트
    if book_type:
        genre_file = BOOK_TYPE_GENRE_FILE_MAP.get(book_type)
        if not genre_file:
            raise PromptBuildError(f"지원하지 않는 bookType입니다: {book_type}")

        prompt_paths.append(f"genre/{genre_file}")

    # 4. 제작 방식별 프롬프트
    if interaction_mode:
        interaction_file = INTERACTION_MODE_FILE_MAP.get(interaction_mode)
        if not interaction_file:
            raise PromptBuildError(f"지원하지 않는 interactionMode입니다: {interaction_mode}")

        prompt_paths.append(f"interaction_mode/{interaction_file}")

    # 5. 현재 작업 task 프롬프트
    if not task_type:
        raise PromptBuildError("taskType이 없습니다.")

    task_file = TASK_FILE_MAP.get(task_type)
    if not task_file:
        raise PromptBuildError(f"지원하지 않는 taskType입니다: {task_type}")

    prompt_paths.append(task_file)

    # 6. 파일 내용 읽어서 합치기
    prompt_parts = []

    for path in prompt_paths:
        content = read_prompt_file(path)
        prompt_parts.append(f"\n\n### {path}\n{content}")

    # 7. 마지막에 실제 요청 JSON 붙이기
    request_json = json.dumps(request_data, ensure_ascii=False, indent=2)

    prompt_parts.append(
        f"""
        
### INPUT_REQUEST_JSON
아래 JSON은 React에서 전달된 실제 요청 데이터이다.
이 요청의 taskType, draft, extra를 기준으로 응답을 생성하라.

{request_json}
"""
    )

    return "\n".join(prompt_parts)