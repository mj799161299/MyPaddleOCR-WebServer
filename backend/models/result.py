from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from database import Base


class OCRResult(Base):
    __tablename__ = "ocr_results"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("ocr_tasks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    image_path = Column(String(500), nullable=False)
    image_name = Column(String(255), nullable=False)
    markdown_text = Column(Text, default="")
    json_data = Column(JSON, default=dict)
    status = Column(String(20), default="pending")  # pending, completed, failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    user = relationship("User")
    task = relationship("OCRTask", back_populates="results")
