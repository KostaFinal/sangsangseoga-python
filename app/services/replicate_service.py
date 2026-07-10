# app/services/replicate_service.py

import asyncio
import os

import replicate
from dotenv import load_dotenv


load_dotenv()


REPLICATE_MODEL = "black-forest-labs/flux-schnell"


class ReplicateServiceError(Exception):
    pass


def _get_client() -> replicate.Client:
    # gemini_service.py와 달리 모듈 로드 시점이 아니라 호출 시점에 토큰을 검사한다.
    # REPLICATE_API_TOKEN이 아직 없어도 텍스트 생성(/api/ai/generate)은 영향받지 않아야 하기 때문.
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        raise ReplicateServiceError("REPLICATE_API_TOKEN이 .env에 설정되어 있지 않습니다.")
    return replicate.Client(api_token=token)


def _run_replicate_sync(prompt: str, aspect_ratio: str) -> str:
    """
    replicate 공식 python 클라이언트는 동기(sync) 함수라, 이 함수는
    generate_image()에서 run_in_executor로 별도 스레드에 위임되는 것을 전제로 한다.
    """
    client = _get_client()

    output = client.run(
        REPLICATE_MODEL,
        input={
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "num_outputs": 1,
            "output_format": "webp",
        },
    )

    first = output[0] if isinstance(output, list) else output

    if first is None:
        raise ReplicateServiceError("Replicate가 빈 결과를 반환했습니다.")

    # 최신 replicate client는 URL 문자열 대신 FileOutput 객체를 반환할 수 있어 str() 변환으로 URL을 얻는다.
    image_url = str(first)

    if not image_url.startswith("http"):
        raise ReplicateServiceError(f"Replicate 응답에서 이미지 URL을 찾지 못했습니다: {image_url!r}")

    return image_url


async def generate_image(prompt: str, aspect_ratio: str = "3:4") -> str:
    """
    Replicate(flux-schnell)를 호출해 이미지 URL 1개를 반환한다.

    # TODO(확장 포인트): 여기서 반환하는 URL은 Replicate의 임시 delivery URL이다.
    # 실제 서비스 연동 시 Spring Boot 쪽(또는 여기)에서 이 URL을 다운로드해 S3 등
    # 영구 스토리지에 재업로드한 뒤, 그 영구 URL을 book_image에 저장해야 한다.
    """
    loop = asyncio.get_running_loop()

    try:
        return await loop.run_in_executor(None, _run_replicate_sync, prompt, aspect_ratio)
    except ReplicateServiceError:
        raise
    except Exception as e:
        raise ReplicateServiceError(f"Replicate 호출 중 오류가 발생했습니다: {str(e)}")
