from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    role = Column(String(10), default="user")  # "admin" or "user"
    is_active = Column(Boolean, default=True)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # 邀请人ID
    invitation_code_id = Column(Integer, ForeignKey("invitation_codes.id"), nullable=True)  # 使用的邀请码ID
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
