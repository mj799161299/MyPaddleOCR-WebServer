import secrets
import string
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from models.invitation_code import InvitationCode
from utils.security import get_current_user, require_admin

router = APIRouter(prefix="/api/admin/invitation-codes", tags=["邀请码管理"])


def generate_invitation_code(length: int = 8) -> str:
    """生成随机邀请码"""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@router.post("/", summary="创建邀请码")
async def create_invitation_code(
    max_uses: int = 1,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员创建邀请码
    
    Args:
        max_uses: 最大使用次数，默认1次
    """
    # 生成唯一邀请码
    for _ in range(10):
        code = generate_invitation_code()
        existing = db.query(InvitationCode).filter(InvitationCode.code == code).first()
        if not existing:
            break
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="无法生成唯一邀请码"
        )
    
    invitation = InvitationCode(
        code=code,
        max_uses=max_uses,
        created_by=current_user.id,
        is_active=True
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    
    return {
        "id": invitation.id,
        "code": invitation.code,
        "max_uses": invitation.max_uses,
        "used_count": invitation.used_count,
        "is_active": invitation.is_active,
        "created_at": invitation.created_at
    }


@router.get("/", summary="获取邀请码列表")
async def list_invitation_codes(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员查看所有邀请码及其使用次数"""
    codes = db.query(InvitationCode).order_by(InvitationCode.created_at.desc()).all()
    
    result = []
    for code in codes:
        # 获取使用该邀请码的用户列表
        users = db.query(User).filter(User.invitation_code_id == code.id).all()
        
        result.append({
            "id": code.id,
            "code": code.code,
            "max_uses": code.max_uses,
            "used_count": code.used_count,
            "is_active": code.is_active,
            "created_at": code.created_at,
            "used_by": [{"id": u.id, "username": u.username, "created_at": u.created_at} for u in users]
        })
    
    return {"codes": result, "total": len(result)}


@router.delete("/{code_id}", summary="删除邀请码")
async def delete_invitation_code(
    code_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员删除邀请码"""
    code = db.query(InvitationCode).filter(InvitationCode.id == code_id).first()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="邀请码不存在"
        )
    
    db.delete(code)
    db.commit()
    
    return {"message": "邀请码已删除"}


@router.get("/users", summary="查看所有用户")
async def list_all_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员查看所有用户及其使用记录"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    
    result = []
    for user in users:
        # 获取邀请人信息
        inviter = None
        if user.invited_by:
            inviter_user = db.query(User).filter(User.id == user.invited_by).first()
            if inviter_user:
                inviter = inviter_user.username
        
        # 获取使用的邀请码
        invitation_code = None
        if user.invitation_code_id:
            code = db.query(InvitationCode).filter(InvitationCode.id == user.invitation_code_id).first()
            if code:
                invitation_code = code.code
        
        # 统计用户的OCR任务数
        from models.task import OCRTask
        task_count = db.query(OCRTask).filter(OCRTask.user_id == user.id).count()
        
        result.append({
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "is_active": user.is_active,
            "inviter": inviter,
            "invitation_code": invitation_code,
            "task_count": task_count,
            "created_at": user.created_at
        })
    
    return {"users": result, "total": len(result)}


@router.post("/{code_id}/toggle", summary="启用/禁用邀请码")
async def toggle_invitation_code(
    code_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理员启用或禁用邀请码"""
    code = db.query(InvitationCode).filter(InvitationCode.id == code_id).first()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="邀请码不存在"
        )
    
    code.is_active = not code.is_active
    db.commit()
    
    return {
        "id": code.id,
        "code": code.code,
        "is_active": code.is_active,
        "message": "邀请码已" + ("启用" if code.is_active else "禁用")
    }
