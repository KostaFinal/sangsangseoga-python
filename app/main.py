# app/main.py

import json
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.schemas.image_request import AiGenerateImageRequest
from app.services.prompt_builder import build_prompt, PromptBuildError
from app.services.gemini_service import call_gemini, stream_gemini, GeminiServiceError
from app.services.image_prompt_builder import build_image_prompt, ImagePromptBuildError
from app.services.replicate_service import generate_image, ReplicateServiceError
from app.utils.perf_logger import log_ai_perf
from app.services.gemini_image_service import generate_image, GeminiImageServiceError


app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def perf_timing_middleware(request: Request, call_next):
    """
    [AI-PERF] 계측용 미들웨어.
    - request.state.perf_start: 요청 수신 시각(라우팅/Pydantic 검증 시작 전)
    - request.state.request_id: Spring이 보낸 X-Request-ID를 그대로 사용하고,
      없으면 새로 발급한다. 응답 헤더에도 동일한 값을 실어 보낸다.
    """
    request.state.perf_start = time.perf_counter()
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.get("/")
async def root():
    return {
        "message": "Sangsang Seoga AI server is running"
    }


@app.post("/api/ai/generate")
async def generate_ai_response(request_data: dict, request: Request):
    perf_start = request.state.perf_start
    request_id = request.state.request_id

    # 이 시점까지가 FastAPI의 바디 파싱(dict 변환) + 라우팅 소요시간이다.
    # (이 엔드포인트는 Pydantic 모델이 아닌 dict를 받으므로 실질적인 스키마 검증은 없다.)
    validation_ms = (time.perf_counter() - perf_start) * 1000

    task_type = request_data.get("taskType")

    try:
        prompt, prompt_timings = build_prompt(request_data)

        result, gemini_timings = await call_gemini(
            prompt=prompt,
            expected_task_type=task_type,
        )

        total_ms = (time.perf_counter() - perf_start) * 1000

        log_ai_perf(request_id, task_type, {
            "validationMs": validation_ms,
            "promptFileLoadMs": prompt_timings["promptFileLoadMs"],
            "promptBuildMs": prompt_timings["promptBuildMs"],
            "geminiTotalMs": gemini_timings["geminiTotalMs"],
            "parseMs": gemini_timings["parseMs"],
            "responseBuildMs": gemini_timings["responseBuildMs"],
            "totalMs": total_ms,
        })

        return result

    except PromptBuildError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    except GeminiServiceError as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@app.post("/api/ai/generate-image")
async def generate_ai_image(request: AiGenerateImageRequest, http_request: Request):
    perf_start = http_request.state.perf_start
    request_id = http_request.state.request_id

    # 여기까지가 FastAPI 수신 + Pydantic(AiGenerateImageRequest) 검증 완료 시각이다.
    validation_ms = (time.perf_counter() - perf_start) * 1000

    if request.imageType == "PAGE" and request.pageNo is None:
        raise HTTPException(
            status_code=400,
            detail="imageType이 PAGE일 때는 pageNo가 필요합니다.",
        )

    try:
        prompt_build_start = time.perf_counter()
        final_prompt = build_image_prompt(request.promptText, request.style)
        prompt_build_ms = (time.perf_counter() - prompt_build_start) * 1000

        image_base64, mime_type = await generate_image(
            prompt=final_prompt,
            aspect_ratio=request.aspectRatio,
        )
        return {
            "success": True,
            "message": "이미지 생성 성공",
            "imageUrl": None,
            # data URI 형태로 넣어서 Spring/프론트가 별도 필드 없이 <img src>에 바로 써도 되게 한다.
            "imageBase64": f"data:{mime_type};base64,{image_base64}",
            "usage": {"imageCount": 1},
        }

    except ImagePromptBuildError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except GeminiImageServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _sse_frame(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def _generate_ai_response_stream(request_data: dict, request_id: str, perf_start: float):
    task_type = request_data.get("taskType")

    validation_ms = (time.perf_counter() - perf_start) * 1000

    try:
        prompt, prompt_timings = build_prompt(request_data)
    except PromptBuildError as e:
        yield _sse_frame("error", {"message": str(e)})
        return

    async for event in stream_gemini(prompt=prompt, expected_task_type=task_type):
        event_type = event.get("type")

        if event_type == "delta":
            yield _sse_frame("delta", {"text": event.get("text", "")})

        elif event_type == "done":
            total_ms = (time.perf_counter() - perf_start) * 1000
            gemini_timings = event.get("timings", {})

            log_ai_perf(request_id, task_type, {
                "validationMs": validation_ms,
                "promptFileLoadMs": prompt_timings["promptFileLoadMs"],
                "promptBuildMs": prompt_timings["promptBuildMs"],
                "geminiFirstTokenMs": gemini_timings.get("geminiFirstTokenMs"),
                "geminiTotalMs": gemini_timings.get("geminiTotalMs"),
                "parseMs": gemini_timings.get("parseMs"),
                "responseBuildMs": gemini_timings.get("responseBuildMs"),
                "totalMs": total_ms,
            })

            yield _sse_frame("done", event.get("envelope", {}))

        elif event_type == "error":
            total_ms = (time.perf_counter() - perf_start) * 1000
            gemini_timings = event.get("timings", {})

            log_ai_perf(request_id, task_type, {
                "validationMs": validation_ms,
                "promptFileLoadMs": prompt_timings["promptFileLoadMs"],
                "promptBuildMs": prompt_timings["promptBuildMs"],
                "geminiFirstTokenMs": gemini_timings.get("geminiFirstTokenMs"),
                "geminiTotalMs": gemini_timings.get("geminiTotalMs"),
                "totalMs": total_ms,
                "error": True,
            })

            yield _sse_frame("error", {"message": event.get("message", "")})


@app.post("/api/ai/generate/stream")
async def generate_ai_response_stream(request_data: dict, request: Request):
    perf_start = request.state.perf_start
    request_id = request.state.request_id

    return StreamingResponse(
        _generate_ai_response_stream(request_data, request_id, perf_start),
        media_type="text/event-stream",
        headers={"X-Request-ID": request_id},
    )
