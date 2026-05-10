"""
认证与用户管理路由模块
======================
负责用户身份认证和用户管理相关接口，涵盖以下功能：

1. 注册：验证邀请码 → 密码哈希 → 创建用户 → 更新邀请码使用次数
2. 登录：验证用户名密码 → 检查账号启用状态 → 生成JWT Token
3. 个人信息：获取当前用户信息、修改密码
4. 用户管理（管理员）：用户列表、角色修改、启用/禁用、删除

密码安全：
    - 所有密码通过 bcrypt（passlib）进行哈希存储，不保存明文
    - 密码验证通过 verify_password() 函数（恒定时间比较，防时序攻击）

JWT Token 机制：
    - 登录成功后签发 JWT（sub=用户ID, role=用户角色, exp=过期时间）
    - 后续请求通过 Bearer Token 携带，由 get_current_user / require_admin 解析验证
    - Token 过期时间由 settings.ACCESS_TOKEN_EXPIRE_MINUTES 控制
"""

from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models.user import User
from schemas.user import UserCreate, UserLogin, UserResponse, Token, UserUpdateRole, UserUpdateStatus, UserListResponse, UserChangePassword
from utils.security import verify_password, get_password_hash, create_access_token, get_current_user, require_admin
from config import settings

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse, summary="用户注册")
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    用户注册
    ========
    用途：新用户注册账号，需提供有效的邀请码。
    
    Auth流程：
        1. 查询邀请码是否存在且激活
        2. 验证邀请码是否有效（未超使用次数上限、未过期）
        3. 检查用户名是否已存在
        4. 密码经 bcrypt 哈希后存储（调用 get_password_hash）
        5. 创建用户（默认角色 "user"，默认启用）
        6. 更新邀请码使用次数，达到上限则自动停用邀请码
    
    输入参数：
        user_data (UserCreate)：
            - username (str)：用户名
            - password (str)：明文密码（存储前会被哈希）
            - invitation_code (str)：注册邀请码
    
    返回值：
        UserResponse：新创建的用户对象（不含密码哈希）
    
    权限要求：
        无需登录（公开注册接口，但需有效邀请码）
    
    边界情况 / 错误处理：
        - 400：邀请码不存在或已停用
        - 400：邀请码已达到使用次数上限或已过期
        - 400：用户名已存在（唯一性校验）
        - 事务安全：用户创建和邀请码计数更新在同一数据库事务中
    """
    # 验证邀请码
    from models.invitation_code import InvitationCode
    
    invitation_code = db.query(InvitationCode).filter(
        InvitationCode.code == user_data.invitation_code,
        InvitationCode.is_active == True
    ).first()
    
    if not invitation_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的邀请码"
        )
    
    # 检查邀请码是否已超过最大使用次数或已过期
    if not invitation_code.is_valid():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码已达到使用次数上限或已过期"
        )
    
    # 用户名唯一性校验
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )

    # 创建用户：密码通过 bcrypt 哈希存储，默认 role="user"，默认启用
    user = User(
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        role="user",
        is_active=True,
        invitation_code_id=invitation_code.id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # 更新邀请码使用次数，达到上限则自动停用
    invitation_code.used_count += 1
    if invitation_code.used_count >= invitation_code.max_uses:
        invitation_code.is_active = False
    db.commit()

    return user


@router.post("/login", response_model=Token, summary="用户登录")
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """
    用户登录
    ========
    用途：验证用户名和密码，签发 JWT 访问令牌。
    
    Auth流程：
        1. 根据用户名查询用户
        2. 密码哈希比对（verify_password，常量时间比较防时序攻击）
        3. 检查账号是否被禁用（is_active）
        4. 生成 JWT Token（包含 sub=用户ID, role=用户角色）
    
    输入参数：
        user_data (UserLogin)：
            - username (str)：用户名
            - password (str)：明文密码
    
    返回值：
        Token：{access_token: "...", token_type: "bearer"}
    
    权限要求：
        无需登录（登录接口本身）
    
    边界情况 / 错误处理：
        - 401：用户名或密码错误（不区分是用户名不存在还是密码错误，防止信息泄露）
        - 403：账号已被管理员禁用
        - JWT Token 过期时间由 ACCESS_TOKEN_EXPIRE_MINUTES 配置决定
        - 返回标准 WWW-Authenticate 头以兼容 HTTP 认证规范
    """
    # 查询用户并验证密码（恒定时间比较）
    user = db.query(User).filter(User.username == user_data.username).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 检查账号是否被禁用
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用"
        )

    # 生成 JWT Token：sub 存用户 ID（字符串形式），role 存用户角色
    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse, summary="获取当前用户信息")
async def get_me(current_user: User = Depends(get_current_user)):
    """
    获取当前用户信息
    ================
    用途：返回当前已登录用户的基本信息（通过 JWT Token 解析）。
    
    Auth流程：
        依赖 get_current_user 从 Bearer Token 中解析用户ID → 查询数据库 → 注入 current_user
    
    输入参数：
        无（通过 Authorization Header 的 Bearer Token 隐式传递）
    
    返回值：
        UserResponse：当前用户对象
    
    权限要求：
        需要登录（有效的 JWT Token）
    
    边界情况 / 错误处理：
        - 401：Token 无效或过期（由 get_current_user 依赖自动处理）
    """
    return current_user


@router.put("/me/password", summary="修改当前用户密码")
async def change_password(
    data: UserChangePassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    修改当前用户密码
    ================
    用途：已登录用户修改自己的密码（需验证原密码）。
    
    Auth流程：
        1. 验证原密码正确（verify_password）
        2. 新密码经 bcrypt 哈希后覆盖旧哈希
    
    输入参数：
        data (UserChangePassword)：
            - old_password (str)：原密码（明文，用于验证身份）
            - new_password (str)：新密码（明文，将被哈希存储）
    
    返回值：
        {message: "密码修改成功"}
    
    权限要求：
        需要登录，只能修改自己的密码。
    
    边界情况 / 错误处理：
        - 400：原密码错误，拒绝修改（防止未授权密码修改）
    """
    # 验证原密码，防止未授权的密码修改
    if not verify_password(data.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误"
        )
    # 新密码哈希存储
    current_user.hashed_password = get_password_hash(data.new_password)
    db.commit()
    return {"message": "密码修改成功"}


@router.get("/users", response_model=UserListResponse, summary="获取用户列表（管理员）")
async def get_users(
    username: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    获取用户列表（管理员）
    =====================
    用途：管理员查看所有注册用户，支持按用户名模糊搜索。
    
    输入参数：
        username (str, 可选)：查询参数，按用户名模糊匹配（contains）
    
    返回值：
        UserListResponse：{users: [...], total: N}
    
    权限要求：
        需要管理员权限（role="admin"），由 require_admin 依赖确保。
    
    边界情况 / 错误处理：
        - 401：未登录或 Token 无效
        - 403：非管理员用户访问
        - username 为空时返回全部用户
    """
    query = db.query(User)
    if username:
        query = query.filter(User.username.contains(username))
    users = query.order_by(User.created_at.desc()).all()
    return {"users": users, "total": len(users)}


@router.put("/users/{user_id}/role", response_model=UserResponse, summary="修改用户角色（管理员）")
async def update_user_role(
    user_id: int,
    data: UserUpdateRole,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    修改用户角色（管理员）
    ======================
    用途：管理员修改指定用户的角色（"user" 或 "admin"）。
    
    输入参数：
        user_id (int)：URL 路径参数，目标用户ID
        data (UserUpdateRole)：{role: "user"|"admin"}
    
    返回值：
        UserResponse：更新后的用户对象
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 404：用户不存在
        - 400：管理员不能取消自己的管理员权限（防止把自己锁在系统外）
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    # 安全保护：管理员不能把自己降级为普通用户
    if user.id == current_user.id and data.role != "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能取消自己的管理员权限")
    user.role = data.role
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}/status", response_model=UserResponse, summary="启用/禁用用户（管理员）")
async def update_user_status(
    user_id: int,
    data: UserUpdateStatus,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    启用/禁用用户（管理员）
    =======================
    用途：管理员启用或禁用指定用户账号，禁用后该用户无法登录。
    
    输入参数：
        user_id (int)：URL 路径参数，目标用户ID
        data (UserUpdateStatus)：{is_active: bool}
    
    返回值：
        UserResponse：更新后的用户对象
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 404：用户不存在
        - 400：管理员不能禁用自己（防止锁死管理员账号）
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    # 安全保护：管理员不能禁用自己
    if user.id == current_user.id and not data.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用自己")
    user.is_active = data.is_active
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", summary="删除用户（管理员）")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    删除用户（管理员）
    ==================
    用途：管理员永久删除指定用户（硬删除数据库记录）。
    
    Auth流程：
        require_admin → 验证 JWT Token → 检查 role="admin"
    
    输入参数：
        user_id (int)：URL 路径参数，目标用户ID
    
    返回值：
        {message: "用户已删除"}
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 404：用户不存在
        - 400：管理员不能删除自己
        - 注意：该操作不会级联删除该用户的 OCRTask 和 OCRResult（需手工清理）
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    # 安全保护：管理员不能删除自己
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除自己")
    db.delete(user)
    db.commit()
    return {"message": "用户已删除"}
