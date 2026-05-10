from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from database import Base


class InvitationCode(Base):
    """邀请码模型"""
    __tablename__ = "invitation_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    max_uses = Column(Integer, default=1)  # 最大使用次数
    used_count = Column(Integer, default=0)  # 已使用次数
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)  # 创建者（管理员）
    is_active = Column(Boolean, default=True)  # 是否有效
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # 过期时间（可选）

    def is_valid(self):
        """检查邀请码是否有效"""
        if not self.is_active:
            return False
        if self.used_count >= self.max_uses:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True
