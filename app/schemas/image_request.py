# app/schemas/image_request.py

from typing import Optional

from pydantic import BaseModel


class AiGenerateImageRequest(BaseModel):
    promptText: str
    imageType: str
    pageNo: Optional[int] = None
    style: Optional[str] = None
    aspectRatio: str = "3:4"
    bookType: Optional[str] = None
    # 캐릭터 일관성용 레퍼런스 이미지(예: 이미 생성된 표지). Spring이 로컬에 저장된 파일을 읽어
    # base64로 실어 보낸다. 없으면(표지 자체를 만들 때 등) 지금까지처럼 텍스트만으로 생성한다.
    referenceImageBase64: Optional[str] = None
    referenceImageMimeType: Optional[str] = None
