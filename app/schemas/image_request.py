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
