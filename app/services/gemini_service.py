# app/services/gemini_service.py

import json
import os
from typing import Any, AsyncGenerator, Dict, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


class GeminiServiceError(Exception):
    pass


if not GEMINI_API_KEY:
    raise GeminiServiceError("GEMINI_API_KEY가 .env에 설정되어 있지 않습니다.")


client = genai.Client(api_key=GEMINI_API_KEY)


def _remove_code_fence(text: str) -> str:
    """
    Gemini가 실수로 ```json 코드블록을 붙였을 때 제거한다.
    json_rule.txt에서 금지했지만, 안전장치로 둔다.
    """
    cleaned = text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned.removeprefix("```json").strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()

    if cleaned.endswith("```"):
        cleaned = cleaned.removesuffix("```").strip()

    return cleaned


def _failed_response(
    task_type: Optional[str],
    message: str,
    warning: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "status": "FAILED",
        "taskType": task_type or "",
        "message": message,
        "result": {},
        "missingFields": [],
        "warnings": [warning] if warning else [],
        "nextAction": "",
    }


def _validate_envelope(data: Dict[str, Any], expected_task_type: Optional[str]) -> Dict[str, Any]:
    """
    React가 항상 같은 구조로 받을 수 있게 응답 envelope를 보정한다.
    """
    required_keys = [
        "status",
        "taskType",
        "message",
        "result",
        "missingFields",
        "warnings",
        "nextAction",
    ]

    for key in required_keys:
        if key not in data:
            if key == "status":
                data[key] = "FAILED"
            elif key == "taskType":
                data[key] = expected_task_type or ""
            elif key == "message":
                data[key] = "AI 응답 형식이 일부 누락되었습니다."
            elif key == "result":
                data[key] = {}
            elif key in ["missingFields", "warnings"]:
                data[key] = []
            elif key == "nextAction":
                data[key] = ""

    if expected_task_type and data.get("taskType") != expected_task_type:
        data["warnings"].append(
            f"응답 taskType이 요청 taskType과 달라 보정했습니다. 원래 값: {data.get('taskType')}"
        )
        data["taskType"] = expected_task_type

    if data["status"] not in ["SUCCESS", "NEED_MORE_INPUT", "FAILED"]:
        data["warnings"].append(f"지원하지 않는 status 값이 있어 FAILED로 보정했습니다. 원래 값: {data['status']}")
        data["status"] = "FAILED"

    if not isinstance(data["result"], dict):
        data["warnings"].append("result가 객체가 아니어서 빈 객체로 보정했습니다.")
        data["result"] = {}

    if not isinstance(data["missingFields"], list):
        data["missingFields"] = []

    if not isinstance(data["warnings"], list):
        data["warnings"] = []

    return data


async def call_gemini(prompt: str, expected_task_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Gemini에 최종 prompt를 보내고, JSON 응답을 dict로 반환한다.
    """

    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
            ),
        )

        raw_text = response.text or ""
        cleaned_text = _remove_code_fence(raw_text)

        try:
            parsed = json.loads(cleaned_text)
        except json.JSONDecodeError:
            return _failed_response(
                task_type=expected_task_type,
                message="AI 응답을 JSON으로 해석하지 못했습니다.",
                warning=cleaned_text[:500],
            )

        if not isinstance(parsed, dict):
            return _failed_response(
                task_type=expected_task_type,
                message="AI 응답이 JSON 객체 형식이 아닙니다.",
                warning=str(parsed)[:500],
            )

        return _validate_envelope(parsed, expected_task_type)

    except Exception as e:
        raise GeminiServiceError(f"Gemini 호출 중 오류가 발생했습니다: {str(e)}")


async def stream_gemini(
    prompt: str, expected_task_type: Optional[str] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Gemini를 스트리밍으로 호출한다. call_gemini와 달리 예외를 던지지 않고,
    모든 결과를 {"type": "delta"|"done"|"error", ...} 형태로 yield한다.

    - delta: 조각난 원문 텍스트 (0회 이상)
    - done: 검증된 envelope 딕셔너리 (성공 시 정확히 1회)
    - error: 실패 메시지 (실패 시 done 대신 정확히 1회)
    """
    accumulated_text = ""

    try:
        stream = await client.aio.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
            ),
        )

        async for chunk in stream:
            text = chunk.text or ""
            if not text:
                continue
            accumulated_text += text
            yield {"type": "delta", "text": text}

    except Exception as e:
        yield {
            "type": "error",
            "message": f"Gemini 스트리밍 호출 중 오류가 발생했습니다: {str(e)}",
        }
        return

    cleaned_text = _remove_code_fence(accumulated_text)

    try:
        parsed = json.loads(cleaned_text)
    except json.JSONDecodeError:
        yield {
            "type": "done",
            "envelope": _failed_response(
                task_type=expected_task_type,
                message="AI 응답을 JSON으로 해석하지 못했습니다.",
                warning=cleaned_text[:500],
            ),
        }
        return

    if not isinstance(parsed, dict):
        yield {
            "type": "done",
            "envelope": _failed_response(
                task_type=expected_task_type,
                message="AI 응답이 JSON 객체 형식이 아닙니다.",
                warning=str(parsed)[:500],
            ),
        }
        return

    yield {"type": "done", "envelope": _validate_envelope(parsed, expected_task_type)}