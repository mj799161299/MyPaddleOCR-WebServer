from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional, Any


class ResultResponse(BaseModel):
    id: int
    task_id: int
    image_path: str
    image_name: str
    markdown_text: str
    json_data: Any
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ResultListResponse(BaseModel):
    results: List[ResultResponse]
    total: int


class ExportRequest(BaseModel):
    result_ids: List[int]
    format: str  # markdown, json, html, word
    original: bool = False  # True=原始PaddleOCR输出, False=修正后（含裸LaTeX包裹）
