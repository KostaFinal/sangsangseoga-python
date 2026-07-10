# app/main.py

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.schemas.image_request import AiGenerateImageRequest
from app.services.prompt_builder import build_prompt, PromptBuildError
from app.services.gemini_service import call_gemini, stream_gemini, GeminiServiceError
from app.services.image_prompt_builder import build_image_prompt, ImagePromptBuildError
from app.services.replicate_service import generate_image, ReplicateServiceError


app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "Sangsang Seoga AI server is running"
    }


@app.post("/api/ai/generate")
async def generate_ai_response(request_data: dict):
    try:
        task_type = request_data.get("taskType")

        prompt = build_prompt(request_data)

        result = await call_gemini(
            prompt=prompt,
            expected_task_type=task_type,
        )

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
async def generate_ai_image(request: AiGenerateImageRequest):
    if request.imageType == "PAGE" and request.pageNo is None:
        raise HTTPException(
            status_code=400,
            detail="imageType이 PAGE일 때는 pageNo가 필요합니다.",
        )

    try:
        final_prompt = build_image_prompt(request.promptText, request.style)

        image_url = await generate_image(
            prompt=final_prompt,
            aspect_ratio=request.aspectRatio,
        )

        return {
            "success": True,
            "message": "이미지 생성 성공",
            "imageUrl": image_url,
            "imageBase64": None,
        }

    except ImagePromptBuildError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except ReplicateServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _sse_frame(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def _generate_ai_response_stream(request_data: dict):
    task_type = request_data.get("taskType")

    try:
        prompt = build_prompt(request_data)
    except PromptBuildError as e:
        yield _sse_frame("error", {"message": str(e)})
        return

    async for event in stream_gemini(prompt=prompt, expected_task_type=task_type):
        event_type = event.get("type")

        if event_type == "delta":
            yield _sse_frame("delta", {"text": event.get("text", "")})
        elif event_type == "done":
            yield _sse_frame("done", event.get("envelope", {}))
        elif event_type == "error":
            yield _sse_frame("error", {"message": event.get("message", "")})


@app.post("/api/ai/generate/stream")
async def generate_ai_response_stream(request_data: dict):
    return StreamingResponse(
        _generate_ai_response_stream(request_data),
        media_type="text/event-stream",
    )