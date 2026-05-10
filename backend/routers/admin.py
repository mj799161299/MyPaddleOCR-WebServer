"""
管理员路由模块
==============
提供管理员视角的全量数据管理和统计功能，所有接口均需 `require_admin` 权限。

数据流概述：
-----------
1. 任务管理：查看/删除所有用户的任务（含已软删除的任务，与用户端不同）
2. 结果管理：查看/删除所有用户的识别结果
3. 统计汇总：提供全局数据统计面板（用户数、任务数、结果数）

管理员删除 vs 用户删除：
    - 用户删除（ocr.py）：软删除，仅标记 deleted_at，不实际删除记录
    - 管理员删除（admin.py）：硬删除，从数据库永久移除，并级联清理关联结果

辅助函数：
    - _task_to_dict()：将 OCRTask ORM 对象转为字典，附加用户名信息
    - _result_to_dict()：将 OCRResult ORM 对象转为字典，附加用户名信息
      这两个函数用于绕过 Pydantic 序列化限制，手动控制返回字段。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional

from database import get_db
from models.user import User
from models.task import OCRTask
from models.result import OCRResult
from schemas.task import BatchIds
from utils.security import require_admin

router = APIRouter(prefix="/api/admin", tags=["管理"])


def _task_to_dict(task):
    """
    将 OCRTask ORM 对象转为字典
    ============================
    用途：手动将 SQLAlchemy 查询结果转为可 JSON 序列化的字典，绕过 Pydantic 响应模型的限制。
    同时将关联的 User 对象的 username 提取到顶层，方便前端展示。
    
    包含字段：id, user_id, username, status, total_images, processed_images, created_at, updated_at
    
    边界处理：
        - 如果 task.user 为 None（用户已被删除），username 显示 "未知"
        - created_at / updated_at 为 None 时保留 None（使用条件表达式安全处理）
    
    参数：
        task：已通过 joinedload(OCRTask.user) 预加载的 OCRTask 对象
    """
    return {
        "id": task.id,
        "user_id": task.user_id,
        "username": task.user.username if task.user else "未知",
        "status": task.status,
        "total_images": task.total_images,
        "processed_images": task.processed_images,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _result_to_dict(result):
    """
    将 OCRResult ORM 对象转为字典
    ==============================
    用途：手动将 SQLAlchemy 查询结果转为可 JSON 序列化的字典。
    将关联的用户名提取到顶层，同时保留 markdown_text 和 json_data 等核心字段。
    
    包含字段：id, task_id, user_id, username, image_path, image_name,
              markdown_text, json_data, status, error_message, created_at
    
    边界处理：
        - 如果 result.user 为 None，username 显示 "未知"
        - created_at 为 None 时保留 None
    
    参数：
        result：已通过 joinedload(OCRResult.user) 预加载的 OCRResult 对象
    """
    return {
        "id": result.id,
        "task_id": result.task_id,
        "user_id": result.user_id,
        "username": result.user.username if result.user else "未知",
        "image_path": result.image_path,
        "image_name": result.image_name,
        "markdown_text": result.markdown_text,
        "json_data": result.json_data,
        "status": result.status,
        "error_message": result.error_message,
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


@router.get("/tasks", summary="查看所有用户任务（管理员）")
async def get_all_tasks(
    username: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    查看所有用户任务（管理员）
    ==========================
    用途：管理员查看系统中所有用户的任务，支持按用户名筛选。
    
    输入参数：
        username (str, 可选)：查询参数，按用户名模糊搜索（contains）
    
    返回值：
        {tasks: [{...}, ...], total: N}，每个任务字典由 _task_to_dict() 生成，包含 username 字段
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 使用 joinedload(OCRTask.user) 预加载关联用户，避免 N+1 查询
        - username 为空时返回全部任务（不含限制，管理后台全量展示）
        - 已软删除的任务（deleted_at != None）也包含在结果中
    """
    query = db.query(OCRTask).options(joinedload(OCRTask.user))
    if username:
        query = query.join(User).filter(User.username.contains(username))
    tasks = query.order_by(OCRTask.created_at.desc()).all()
    return {"tasks": [_task_to_dict(t) for t in tasks], "total": len(tasks)}


@router.get("/tasks/{task_id}/results", summary="查看任务的结果列表（管理员）")
async def get_task_results(
    task_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    查看任务的结果列表（管理员）
    ============================
    用途：管理员查看指定任务下的所有识别结果。
    
    输入参数：
        task_id (int)：URL 路径参数，任务ID
    
    返回值：
        {results: [{...}, ...], total: N}，每个结果字典由 _result_to_dict() 生成
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 404：任务不存在
        - 使用 joinedload(OCRResult.user) 预加载关联用户
        - 结果按创建时间降序排列
    """
    task = db.query(OCRTask).filter(OCRTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    results = db.query(OCRResult).options(joinedload(OCRResult.user)).filter(
        OCRResult.task_id == task_id
    ).order_by(OCRResult.created_at.desc()).all()
    return {"results": [_result_to_dict(r) for r in results], "total": len(results)}


@router.delete("/tasks/{task_id}", summary="删除识别任务（管理员硬删除）")
async def delete_task(
    task_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    删除识别任务（管理员硬删除）
    ============================
    用途：管理员永久删除指定任务及其所有关联的识别结果（级联删除）。
    
    级联机制：
        OCRTask 与 OCRResult 之间存在外键关系（result.task_id → task.id），
        且外键定义了 ON DELETE CASCADE，因此删除任务时会自动删除其下所有结果。
    
    输入参数：
        task_id (int)：URL 路径参数，任务ID
    
    返回值：
        {message: "任务已删除"}
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 404：任务不存在
        - 与用户端删除不同：此处是数据库硬删除，不可恢复
        - 级联删除所有关联的 OCRResult 记录
    """
    task = db.query(OCRTask).filter(OCRTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    db.delete(task)
    db.commit()
    return {"message": "任务已删除"}


@router.post("/tasks/batch-delete", summary="批量删除识别任务（管理员）")
async def batch_delete_tasks(
    data: BatchIds,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    批量删除识别任务（管理员硬删除）
    ================================
    用途：管理员批量永久删除多个任务，每个任务级联删除其关联结果。
    
    级联机制：
        逐个删除任务时，每个任务的 OCRResult 也会因外键 ON DELETE CASCADE 被自动删除。
    
    输入参数：
        data (BatchIds)：{ids: [int, ...]}，要删除的任务ID列表
    
    返回值：
        {message: "已删除 N 个任务"}
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 不存在的任务ID会被静默忽略（由 db.query...filter(id.in_(data.ids)) 自动过滤）
        - 如果一个任务都没有匹配到，消息中 N=0
    """
    tasks = db.query(OCRTask).filter(OCRTask.id.in_(data.ids)).all()
    for task in tasks:
        db.delete(task)
    db.commit()
    return {"message": f"已删除 {len(tasks)} 个任务"}


@router.get("/results", summary="查看所有用户识别结果（管理员）")
async def get_all_results(
    username: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    查看所有用户识别结果（管理员）
    ==============================
    用途：管理员查看系统中所有识别结果，支持按用户名筛选，限制上限 200 条。
    
    输入参数：
        username (str, 可选)：查询参数，按用户名模糊搜索
    
    返回值：
        {results: [{...}, ...], total: N}，最多 200 条，每个结果字典由 _result_to_dict() 生成
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 上限 200 条（防止管理员面板因数据量过大而超时或崩溃）
        - 使用 joinedload(OCRResult.user) 预加载关联用户
    """
    query = db.query(OCRResult).options(joinedload(OCRResult.user))
    if username:
        query = query.join(User).filter(User.username.contains(username))
    results = query.order_by(OCRResult.created_at.desc()).limit(200).all()
    return {"results": [_result_to_dict(r) for r in results], "total": len(results)}


@router.delete("/results/{result_id}", summary="删除识别结果（管理员）")
async def delete_result(
    result_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    删除识别结果（管理员）
    ======================
    用途：管理员硬删除单个识别结果，并在删除后重新计算关联任务的统计信息。
    
    级联逻辑：
        与用户端删除类似（ocr.py），删除结果后：
        - 若任务下无剩余结果 → 删除任务
        - 若仍有结果 → 重新计算 total_images、processed_images、status
    
    输入参数：
        result_id (int)：URL 路径参数，结果ID
    
    返回值：
        {message: "结果已删除"}
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 404：结果不存在
        - 跨用户操作：管理员可以删除任意用户的结果
        - 任务状态同步（同 ocr.py 删除逻辑）
    """
    result = db.query(OCRResult).filter(OCRResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="结果不存在")
    task_id = result.task_id
    db.delete(result)
    db.flush()
    task = db.query(OCRTask).filter(OCRTask.id == task_id).first()
    if task:
        remaining = db.query(OCRResult).filter(OCRResult.task_id == task_id).count()
        if remaining == 0:
            db.delete(task)
        else:
            completed = db.query(OCRResult).filter(OCRResult.task_id == task_id, OCRResult.status == "completed").count()
            failed = db.query(OCRResult).filter(OCRResult.task_id == task_id, OCRResult.status == "failed").count()
            task.total_images = remaining
            task.processed_images = completed
            task.status = "failed" if failed > 0 else "completed"
    db.commit()
    return {"message": "结果已删除"}


@router.post("/results/batch-delete", summary="批量删除识别结果（管理员）")
async def batch_delete_results(
    data: BatchIds,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    批量删除识别结果（管理员）
    ==========================
    用途：管理员批量硬删除多个识别结果，每个删除后同步更新关联任务的统计信息。
    
    级联逻辑：
        对每个被删除的结果：
        1. 硬删除 OCRResult 记录
        2. flush 后立即检查关联任务：
           - 无剩余结果 → 删除任务
           - 有剩余结果 → 重新统计并更新 total_images、processed_images、status
    
    输入参数：
        data (BatchIds)：{ids: [int, ...]}，要删除的结果ID列表
    
    返回值：
        {message: "已删除 N 个结果"}
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 不存在的ID自动忽略
        - 每个结果的删除都独立执行，一个失败不影响其他
        - 同一任务下有多个结果被批量删除时，每次 flush 后会重新统计
    """
    results = db.query(OCRResult).filter(OCRResult.id.in_(data.ids)).all()
    for result in results:
        task_id = result.task_id
        db.delete(result)
        db.flush()
        task = db.query(OCRTask).filter(OCRTask.id == task_id).first()
        if task:
            remaining = db.query(OCRResult).filter(OCRResult.task_id == task_id).count()
            if remaining == 0:
                db.delete(task)
            else:
                completed = db.query(OCRResult).filter(OCRResult.task_id == task_id, OCRResult.status == "completed").count()
                failed = db.query(OCRResult).filter(OCRResult.task_id == task_id, OCRResult.status == "failed").count()
                task.total_images = remaining
                task.processed_images = completed
                task.status = "failed" if failed > 0 else "completed"
    db.commit()
    return {"message": f"已删除 {len(results)} 个结果"}


@router.get("/stats", summary="获取系统统计（管理员）")
async def get_stats(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    获取系统统计（管理员）
    ======================
    用途：提供管理后台数据面板的全局统计信息。
    
    统计指标：
        - user_count：总用户数
        - active_user_count：启用用户数（is_active=True）
        - admin_count：管理员数量（role="admin"）
        - task_count：总任务数
        - completed_task_count：已完成任务数（status="completed"）
        - result_count：总识别结果数
        - completed_result_count：已完成结果数（status="completed"）
    
    输入参数：
        无
    
    返回值：
        {user_count, active_user_count, admin_count, task_count, completed_task_count, result_count, completed_result_count}
    
    权限要求：
        需要管理员权限（require_admin）。
    
    边界情况 / 错误处理：
        - 各计数通过 SQL COUNT 聚合查询获取，无数据时返回 0
        - func.count 保证返回值类型为整数
    """
    user_count = db.query(func.count(User.id)).scalar()
    active_user_count = db.query(func.count(User.id)).filter(User.is_active == True).scalar()
    admin_count = db.query(func.count(User.id)).filter(User.role == "admin").scalar()
    task_count = db.query(func.count(OCRTask.id)).scalar()
    completed_task_count = db.query(func.count(OCRTask.id)).filter(OCRTask.status == "completed").scalar()
    result_count = db.query(func.count(OCRResult.id)).scalar()
    completed_result_count = db.query(func.count(OCRResult.id)).filter(OCRResult.status == "completed").scalar()

    return {
        "user_count": user_count,
        "active_user_count": active_user_count,
        "admin_count": admin_count,
        "task_count": task_count,
        "completed_task_count": completed_task_count,
        "result_count": result_count,
        "completed_result_count": completed_result_count,
    }
