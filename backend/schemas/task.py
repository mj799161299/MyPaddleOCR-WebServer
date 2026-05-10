from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional


class TaskCreate(BaseModel):
    image_ids: List[int]


class TaskResponse(BaseModel):
    id: int
    status: str
    total_images: int
    processed_images: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    tasks: List[TaskResponse]
    total: int


class BatchIds(BaseModel):
    ids: List[int] = Field(..., min_length=1)
