# app/services/gemini_service.py

import json
import os
import time
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# [AI-PERF 실험] gemini-2.5-flash는 기본적으로 "thinking"(응답 전 숨겨진 추론 토큰 생성)이
# 켜져 있어, 출력이 짧은 태스크에서도 지연시간이 크게 나오는 원인으로 의심된다.
# thinking_budget=0으로 비활성화한 뒤 [AI-PERF] 로그로 Before/After를 비교한다.
_THINKING_CONFIG = types.ThinkingConfig(thinking_budget=0)


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


async def call_gemini(
    prompt: str, expected_task_type: Optional[str] = None
) -> Tuple[Dict[str, Any], Dict[str, float]]:
    """
    Gemini에 최종 prompt를 보내고, JSON 응답을 dict로 반환한다.

    반환값: (result, timings)
    timings = {"geminiTotalMs": Gemini 호출 대기시간, "parseMs": JSON 파싱시간, "responseBuildMs": envelope 검증/보정시간}

    [AI-PERF] 계측을 위해 임시로 시그니처를 dict -> (dict, dict)로 바꿨다.
    """

    try:
        gemini_start = time.perf_counter()
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
                thinking_config=_THINKING_CONFIG,
            ),
        )
        gemini_total_ms = (time.perf_counter() - gemini_start) * 1000

        raw_text = response.text or ""
        cleaned_text = _remove_code_fence(raw_text)

        parse_start = time.perf_counter()
        try:
            parsed = json.loads(cleaned_text)
        except json.JSONDecodeError:
            parse_ms = (time.perf_counter() - parse_start) * 1000
            build_start = time.perf_counter()
            result = _failed_response(
                task_type=expected_task_type,
                message="AI 응답을 JSON으로 해석하지 못했습니다.",
                warning=cleaned_text[:500],
            )
            response_build_ms = (time.perf_counter() - build_start) * 1000
            return result, {
                "geminiTotalMs": gemini_total_ms,
                "parseMs": parse_ms,
                "responseBuildMs": response_build_ms,
            }
        parse_ms = (time.perf_counter() - parse_start) * 1000

        build_start = time.perf_counter()
        if not isinstance(parsed, dict):
            result = _failed_response(
                task_type=expected_task_type,
                message="AI 응답이 JSON 객체 형식이 아닙니다.",
                warning=str(parsed)[:500],
            )
        else:
            result = _validate_envelope(parsed, expected_task_type)
        response_build_ms = (time.perf_counter() - build_start) * 1000

        return result, {
            "geminiTotalMs": gemini_total_ms,
            "parseMs": parse_ms,
            "responseBuildMs": response_build_ms,
        }

    except GeminiServiceError:
        raise
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
    stream_start = time.perf_counter()
    first_token_ms: Optional[float] = None

    try:
        stream = await client.aio.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                response_mime_type="application/json",
                thinking_config=_THINKING_CONFIG,
            ),
        )

        async for chunk in stream:
            text = chunk.text or ""
            if not text:
                continue
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - stream_start) * 1000
            accumulated_text += text
            yield {"type": "delta", "text": text}

    except Exception as e:
        yield {
            "type": "error",
            "message": f"Gemini 스트리밍 호출 중 오류가 발생했습니다: {str(e)}",
            "timings": {
                "geminiFirstTokenMs": first_token_ms,
                "geminiTotalMs": (time.perf_counter() - stream_start) * 1000,
            },
        }
        return

    gemini_total_ms = (time.perf_counter() - stream_start) * 1000
    cleaned_text = _remove_code_fence(accumulated_text)

    timings = {
        "geminiFirstTokenMs": first_token_ms,
        "geminiTotalMs": gemini_total_ms,
    }

    parse_start = time.perf_counter()
    try:
        parsed = json.loads(cleaned_text)
    except json.JSONDecodeError:
        timings["parseMs"] = (time.perf_counter() - parse_start) * 1000
        build_start = time.perf_counter()
        envelope = _failed_response(
            task_type=expected_task_type,
            message="AI 응답을 JSON으로 해석하지 못했습니다.",
            warning=cleaned_text[:500],
        )
        timings["responseBuildMs"] = (time.perf_counter() - build_start) * 1000
        yield {"type": "done", "envelope": envelope, "timings": timings}
        return
    timings["parseMs"] = (time.perf_counter() - parse_start) * 1000

    build_start = time.perf_counter()
    if not isinstance(parsed, dict):
        envelope = _failed_response(
            task_type=expected_task_type,
            message="AI 응답이 JSON 객체 형식이 아닙니다.",
            warning=str(parsed)[:500],
        )
    else:
        envelope = _validate_envelope(parsed, expected_task_type)
    timings["responseBuildMs"] = (time.perf_counter() - build_start) * 1000

    yield {"type": "done", "envelope": envelope, "timings": timings}