"""
OCR 识别任务路由模块
====================

OCR 任务生命周期：创建 → 处理 → 轮询 → 获取结果
-------------------------------------------------
1. 【创建阶段】 POST /api/ocr/recognize
   用户提交图片ID列表，创建 OCRTask（状态: PENDING），异步提交到线程池。
   同时将关联的 OCRResult 状态置为 "pending"，绑定 task_id。

2. 【处理阶段】 _process_ocr_sync（后台线程同步执行）
   线程池取出任务 → 状态改为 PROCESSING → 逐张调用 OCR 服务识别 →
   每张图片识别完成后更新 result 的 markdown_text/json_data/status →
   更新 task.processed_images 进度 → 全部完成后标记 COMPLETED 或 FAILED。

3. 【轮询阶段】 GET /api/ocr/tasks 或 GET /api/ocr/tasks/{task_id}
   前端通过轮询任务列表/详情获取实时进度（processed_images / total_images / status）。
   也可通过 WebSocket (/api/ocr/ws/{user_id}) 接收服务端主动推送的进度更新。

4. 【获取结果】 GET /api/ocr/results 或 GET /api/ocr/results/{result_id}
   任务完成后，前端拉取已完成的结果详情（markdown文本、JSON结构化数据等）。

5. 【重试机制】 POST /api/ocr/retry
   对失败或未完成的图片创建新任务重新识别。

6. 【删除机制】
   用户删除：POST/DELETE 标记 deleted_at（软删除），管理员仍可查看。
   管理员删除：在 admin.py 中硬删除，级联删除关联结果。

权限模型：
   所有涉及用户数据的接口均通过 get_current_user 依赖注入验证 JWT Token，
   确保用户只能操作自己的任务和结果。
"""

import asyncio
import os
import re
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session

import logging
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect

from database import get_db, SessionLocal
from models.user import User
from models.task import OCRTask, TaskStatus
from models.result import OCRResult
from schemas.task import TaskCreate, TaskResponse, TaskListResponse, BatchIds
from schemas.result import ResultResponse, ResultListResponse
from utils.security import get_current_user
from services.ocr_service import OCRService

router = APIRouter(prefix="/api/ocr", tags=["OCR识别"])

# WebSocket 连接池：{user_id: WebSocket}，用于向指定用户实时推送识别进度
websocket_connections = {}

logger = logging.getLogger(__name__)

# 单线程执行器：确保 OCR 任务严格按提交顺序串行执行，避免 GPU/CPU 资源争抢
_ocr_executor = ThreadPoolExecutor(max_workers=1)


def _process_ocr_sync(task_id: int, image_ids: List[int], user_id: int):
    """
    OCR 识别流水线（后台线程同步执行）
    ====================================
    该函数在 ThreadPoolExecutor 中运行，负责整个识别管道的实际执行：

    流水线步骤：
    -----------
    1. 获取独立数据库会话（避免与请求线程的会话冲突）
    2. 根据 task_id 加载 OCRTask，将状态置为 PROCESSING
    3. 初始化 OCRService（连接外部 OCR 推理服务器）
    4. 遍历 image_ids：
       a. 加载 OCRResult 记录
       b. 跳过已完成的结果（避免重复识别）
       c. 构建图片存储目录路径（按用户/结果ID组织）
       d. 调用 ocr_service.recognize() 执行 OCR 推理
       e. 将返回的 markdown_text 和 json_data 写入 result 记录
       f. 更新 result.status = "completed"
       g. 异常处理：将 result.status 置为 "failed"，记录错误信息
       h. 更新 task.processed_images 进度计数器
    5. 全部完成后：
       - 存在失败项 → task.status = FAILED（部分失败）
       - 全部成功 → task.status = COMPLETED
    6. finally：关闭数据库会话，释放连接

    错误处理策略：
    -------------
    - 单张图片识别失败不阻断后续图片处理
    - 任务级别异常（如数据库连接丢失）会将整个任务标记为 FAILED
    - 事务回滚：任务级异常时执行 db.rollback()

    参数：
        task_id: OCR 任务ID
        image_ids: 待识别图片的 OCRResult ID 列表
        user_id: 用户ID（用于构建上传目录路径）
    """
    from config import settings
    import traceback

    # 创建独立数据库会话，避免与 FastAPI 请求线程的会话产生竞态
    db = SessionLocal()
    server_url = settings.OCR_SERVER_URL
    task = None

    try:
        # 步骤1：加载任务并标记为处理中
        task = db.query(OCRTask).filter(OCRTask.id == task_id).first()
        if not task:
            return

        task.status = TaskStatus.PROCESSING
        db.commit()

        # 步骤2：初始化 OCR 服务客户端
        ocr_service = OCRService(server_url)
        processed = 0
        has_failure = False

        # 步骤3：逐张图片识别
        for image_id in image_ids:
            result = db.query(OCRResult).filter(OCRResult.id == image_id).first()
            if not result:
                continue

            # 跳过已完成的，避免重复调用外部 OCR 服务
            if result.status == "completed":
                processed += 1
                task.processed_images = processed
                db.commit()
                continue

            try:
                # 构建图片输出目录：uploads/{user_id}/imgs/{result_id}/
                imgs_dir = os.path.join(
                    settings.UPLOAD_DIR, str(user_id), "imgs", str(image_id)
                )
                # 调用 OCR 服务进行推理
                ocr_result = ocr_service.recognize(result.image_path, save_images_dir=imgs_dir)

                # 将识别结果写入数据库
                result.markdown_text = ocr_result.get("markdown_text", "")
                result.json_data = ocr_result.get("json_data", {})
                result.status = "completed"
                result.error_message = None

            except Exception as e:
                # 单张图片识别失败：记录错误，继续处理下一张
                error_msg = str(e)
                full_trace = traceback.format_exc()
                result.status = "failed"
                result.error_message = error_msg
                has_failure = True
                logger.error(f"OCR failed for image {image_id}: {error_msg}\n{full_trace}")

            processed += 1
            task.processed_images = processed
            db.commit()

        # 步骤4：根据执行结果确定最终任务状态
        # 如果存在失败项，标记任务为部分失败
        if has_failure:
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.COMPLETED
        db.commit()

    except Exception as e:
        # 任务级别异常（如数据库崩溃）：标记任务失败并回滚
        logger.error(f"Task {task_id} processing error: {e}\n{traceback.format_exc()}")
        try:
            if task:
                task.status = TaskStatus.FAILED
                db.commit()
        except Exception:
            db.rollback()
    finally:
        # 释放数据库连接
        db.close()


@router.post("/recognize", response_model=TaskResponse, summary="提交识别任务")
async def create_recognize_task(
    task_data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    提交OCR识别任务
    ================
    用途：创建新的 OCR 识别任务，将指定图片加入待处理队列。
    
    输入参数：
        task_data (TaskCreate)：包含 image_ids 列表（要识别的图片ID数组）
    
    返回值：
        TaskResponse：新创建的 OCRTask 对象（id、status=PENDING、total_images、created_at 等）
    
    权限要求：
        需要登录（Bearer Token），用户只能操作自己的图片。
    
    边界情况 / 错误处理：
        - 400：部分图片不存在或不属于当前用户（校验 image_ids 全量归属）
        - 图片数量与查询结果不一致时拒绝创建任务
    """
    # 验证图片是否属于当前用户
    # 边缘情况：如果数据库中存在不属于该用户的 image_id，len 不匹配 → 400
    results = db.query(OCRResult).filter(
        OCRResult.id.in_(task_data.image_ids),
        OCRResult.user_id == current_user.id
    ).all()

    if len(results) != len(task_data.image_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="部分图片不存在或无权限访问"
        )

    # 创建任务
    # 初始状态 PENDING，等待线程池异步处理
    task = OCRTask(
        user_id=current_user.id,
        total_images=len(results),
        status=TaskStatus.PENDING
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 更新图片关联的任务ID
    # 将所有相关 OCRResult 的 task_id 指向新任务，status 重置为 pending
    for result in results:
        result.task_id = task.id
        result.status = "pending"
    db.commit()

    # 异步提交到单线程执行器，不阻塞 HTTP 响应
    _ocr_executor.submit(
        _process_ocr_sync, task.id, task_data.image_ids, current_user.id
    )

    return task


@router.post("/retry", response_model=TaskResponse, summary="重试失败的识别任务")
async def retry_ocr_task(
    task_data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    重试OCR识别任务（仅对失败或未处理的图片）
    =========================================
    用途：为之前识别失败的图片创建新任务，仅重试 "failed" 或 "pending" 状态的图片。
    
    输入参数：
        task_data (TaskCreate)：包含需要重试的 image_ids 列表
    
    返回值：
        TaskResponse：新创建的 OCRTask 对象
    
    权限要求：
        需要登录，用户只能重试自己的图片。
    
    边界情况 / 错误处理：
        - 400：部分图片不存在、无权限、或已成功识别（已成功的不可重试）
        - 已成功的图片被排除在查询条件外（status NOT IN ["failed", "pending"]）
        - 重试前清空 error_message，避免残留旧的错误信息
    """
    # 验证图片是否属于当前用户且状态为失败
    # 仅查询 failed/pending 状态的图片，已完成的不会被重试
    results = db.query(OCRResult).filter(
        OCRResult.id.in_(task_data.image_ids),
        OCRResult.user_id == current_user.id,
        OCRResult.status.in_(["failed", "pending"])
    ).all()

    if len(results) != len(task_data.image_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="部分图片不存在、无权限访问或已成功识别"
        )

    # 创建新任务
    task = OCRTask(
        user_id=current_user.id,
        total_images=len(results),
        status=TaskStatus.PENDING
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 更新图片关联的任务ID和状态
    # 清除旧的 error_message，重置为 pending
    for result in results:
        result.task_id = task.id
        result.status = "pending"
        result.error_message = None
    db.commit()

    _ocr_executor.submit(
        _process_ocr_sync, task.id, task_data.image_ids, current_user.id
    )

    return task


@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """
    WebSocket连接端点，用于实时推送识别进度
    =========================================
    用途：建立 WebSocket 长连接，服务端可向指定用户推送任务进度更新。
    
    输入参数：
        user_id (int)：URL 路径参数，用户ID
    
    返回值：
        无（WebSocket 连接，双向通信）
    
    权限要求：
        无额外鉴权（注意：生产环境应验证 WebSocket 连接的身份 token）
    
    边界情况 / 错误处理：
        - 客户端断开连接（WebSocketDisconnect）时自动从连接池中移除
        - receive_text() 持续阻塞保持连接存活
    """
    await websocket.accept()
    websocket_connections[user_id] = websocket

    try:
        while True:
            # 保持连接
            await websocket.receive_text()
    except WebSocketDisconnect:
        if user_id in websocket_connections:
            del websocket_connections[user_id]


@router.get("/tasks", response_model=TaskListResponse, summary="获取任务列表")
async def get_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取当前用户的任务列表
    =======================
    用途：返回当前用户的所有任务（按创建时间倒序），自动过滤软删除的任务。
    
    输入参数：
        无（仅依赖 JWT Token 中的用户身份）
    
    返回值：
        TaskListResponse：{tasks: [...], total: N}，按 created_at 降序
    
    权限要求：
        需要登录，仅返回当前用户的任务。
    
    边界情况 / 错误处理：
        - 自动排除 deleted_at != None 的记录（用户软删除的任务）
        - 无任务时返回空列表，total = 0
    """
    tasks = db.query(OCRTask).filter(
        OCRTask.user_id == current_user.id,
        OCRTask.deleted_at == None
    ).order_by(OCRTask.created_at.desc()).all()

    return {"tasks": tasks, "total": len(tasks)}


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="获取任务详情")
async def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取指定任务的详情
    ==================
    用途：查看单个 OCR 任务的详细信息，包括进度和状态。
    
    输入参数：
        task_id (int)：URL 路径参数，任务ID
    
    返回值：
        TaskResponse：OCRTask 对象（含 processed_images、total_images、status 等）
    
    权限要求：
        需要登录，只能查看自己的任务。
    
    边界情况 / 错误处理：
        - 404：任务不存在或不属于当前用户
    """
    task = db.query(OCRTask).filter(
        OCRTask.id == task_id,
        OCRTask.user_id == current_user.id
    ).first()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )

    return task


@router.get("/results", response_model=ResultListResponse, summary="获取识别结果列表")
async def get_results(
    task_id: int = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取识别结果列表（仅已完成）
    ============================
    用途：返回当前用户的已完成结果列表，可按任务ID筛选。
    
    输入参数：
        task_id (int, 可选)：查询参数，按任务ID过滤结果
    
    返回值：
        ResultListResponse：{results: [...], total: N}，仅包含 status="completed" 的结果
    
    权限要求：
        需要登录，仅返回当前用户的结果。
    
    边界情况 / 错误处理：
        - 只返回已完成的（status="completed"），失败的被自动过滤
        - task_id 为空时返回该用户所有已完成结果
    """
    query = db.query(OCRResult).filter(
        OCRResult.user_id == current_user.id,
        OCRResult.status == "completed"
    )

    if task_id:
        query = query.filter(OCRResult.task_id == task_id)

    results = query.order_by(OCRResult.created_at.desc()).all()

    return {"results": results, "total": len(results)}


@router.get("/results/all", summary="获取所有识别结果（含失败）")
async def get_all_results(
    task_id: int = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取所有识别结果（包括失败的）
    ==============================
    用途：返回当前用户的所有结果（含失败的），用于重试或排查。
    
    输入参数：
        task_id (int, 可选)：查询参数，按任务ID过滤
    
    返回值：
        {results: [...], total: N}，包含所有状态（completed / failed / pending）
    
    权限要求：
        需要登录，仅返回当前用户的结果。
    
    边界情况 / 错误处理：
        - 失败的结果中包含 error_message 字段供排查
    """
    query = db.query(OCRResult).filter(
        OCRResult.user_id == current_user.id
    )

    if task_id:
        query = query.filter(OCRResult.task_id == task_id)

    results = query.order_by(OCRResult.created_at.desc()).all()

    return {"results": results, "total": len(results)}


@router.get("/results/{result_id}", response_model=ResultResponse, summary="获取识别结果详情")
async def get_result(
    result_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取指定识别结果的详情
    =======================
    用途：查看单个 OCR 结果的完整数据（markdown文本、JSON结构化数据等）。
    
    输入参数：
        result_id (int)：URL 路径参数，结果ID
    
    返回值：
        ResultResponse：OCRResult 对象（含 markdown_text、json_data、status 等）
    
    权限要求：
        需要登录，只能查看自己的结果。
    
    边界情况 / 错误处理：
        - 404：结果不存在或不属于当前用户
    """
    result = db.query(OCRResult).filter(
        OCRResult.id == result_id,
        OCRResult.user_id == current_user.id
    ).first()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="结果不存在"
        )

    return result


@router.delete("/tasks/{task_id}", summary="删除识别任务（用户软删除）")
async def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除识别任务（用户软删除）
    ==========================
    用途：用户删除任务，仅标记 deleted_at 时间戳（软删除），不真正删除数据库记录。
          管理员通过 admin 面板仍可查看已软删除的数据，便于审计和数据恢复。
    
    输入参数：
        task_id (int)：URL 路径参数，任务ID
    
    返回值：
        {message: "任务已删除"}
    
    权限要求：
        需要登录，只能删除自己的任务。
    
    边界情况 / 错误处理：
        - 404：任务不存在或不属于当前用户
        - 与管理员硬删除不同：此处只设置 deleted_at，不删除关联的 OCRResult 记录
    """
    from datetime import datetime
    task = db.query(OCRTask).filter(
        OCRTask.id == task_id,
        OCRTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    task.deleted_at = datetime.utcnow()
    db.commit()
    return {"message": "任务已删除"}


@router.post("/tasks/batch-delete", summary="批量删除识别任务（用户软删除）")
async def batch_delete_tasks(
    data: BatchIds,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量删除识别任务（用户软删除）
    ==============================
    用途：批量软删除当前用户的多个任务，统一标记 deleted_at。
    
    输入参数：
        data (BatchIds)：{ids: [int, ...]}，要删除的任务ID列表
    
    返回值：
        {message: "已删除 N 个任务"}
    
    权限要求：
        需要登录，仅删除自己的任务。
    
    边界情况 / 错误处理：
        - 404：所有给定的任务ID都不属于当前用户时返回错误
        - 部分ID不属于用户时只删除属于用户的（通过 user_id 过滤）
        - 所有被删除的任务使用统一的 deleted_at 时间戳
    """
    from datetime import datetime
    tasks = db.query(OCRTask).filter(
        OCRTask.id.in_(data.ids),
        OCRTask.user_id == current_user.id
    ).all()
    if not tasks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到可删除的任务")
    now = datetime.utcnow()
    for task in tasks:
        task.deleted_at = now
    db.commit()
    return {"message": f"已删除 {len(tasks)} 个任务"}


@router.delete("/results/{result_id}", summary="删除识别结果")
async def delete_result(
    result_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除识别结果
    ============
    用途：硬删除单个 OCRResult 记录。如果删除后该任务下无其他结果，则同时删除任务；
          否则重新计算任务的统计信息（total_images、processed_images、status）。
    
    输入参数：
        result_id (int)：URL 路径参数，结果ID
    
    返回值：
        {message: "结果已删除"}
    
    权限要求：
        需要登录，只能删除自己的结果。
    
    边界情况 / 错误处理：
        - 404：结果不存在或不属于当前用户
        - 删除最后一个结果时，关联的 OCRTask 也被删除（级联清理）
        - 删除非最后一个结果时，重新计算任务的状态和进度：
          * 剩余结果中有 failed → 任务状态改为 FAILED
          * 剩余结果全部 completed → 任务状态改为 COMPLETED
          * total_images 和 processed_images 同步更新
    """
    result = db.query(OCRResult).filter(
        OCRResult.id == result_id,
        OCRResult.user_id == current_user.id
    ).first()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="结果不存在"
        )
    task_id = result.task_id
    db.delete(result)
    db.flush()
    task = db.query(OCRTask).filter(OCRTask.id == task_id).first()
    if task:
        remaining = db.query(OCRResult).filter(OCRResult.task_id == task_id).count()
        if remaining == 0:
            # 任务下无剩余结果，删除任务
            db.delete(task)
        else:
            # 重新统计任务下的结果数量和状态
            completed = db.query(OCRResult).filter(
                OCRResult.task_id == task_id,
                OCRResult.status == "completed"
            ).count()
            failed = db.query(OCRResult).filter(
                OCRResult.task_id == task_id,
                OCRResult.status == "failed"
            ).count()
            task.total_images = remaining
            task.processed_images = completed
            task.status = TaskStatus.FAILED if failed > 0 else TaskStatus.COMPLETED
    db.commit()
    return {"message": "结果已删除"}


@router.get("/status", summary="检查OCR服务状态")
async def check_ocr_status():
    """
    检查OCR服务器连接状态
    =====================
    用途：探测外部 OCR 推理服务器是否可达（健康检查）。
    
    输入参数：
        无
    
    返回值：
        OCRService.check_server() 的返回结果（服务器状态信息）
    
    权限要求：
        无（公开接口，用于运维监控）
    
    边界情况 / 错误处理：
        - 依赖 OCRService.check_server() 内部的异常处理和超时逻辑
    """
    return OCRService.check_server()
