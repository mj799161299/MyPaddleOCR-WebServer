import os
import uuid
import shutil
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from PIL import Image

from database import get_db
from models.user import User
from models.result import OCRResult
from schemas.result import ResultResponse, ResultListResponse
from utils.security import get_current_user
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upload", tags=["上传"])

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
ALLOWED_PDF_EXTENSIONS = {".pdf"}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_PDF_EXTENSIONS


def get_user_upload_dir(user_id: int) -> str:
    """获取用户上传目录"""
    user_dir = os.path.join(settings.UPLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def validate_file(file: UploadFile) -> bool:
    """验证文件类型（支持图片和PDF）"""
    if not file.filename:
        return False
    ext = os.path.splitext(file.filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def is_pdf_file(filename: str) -> bool:
    """判断是否为PDF文件"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_PDF_EXTENSIONS


@router.post("/images", response_model=List[ResultResponse], summary="上传图片或PDF")
async def upload_images(
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """上传一张或多张图片/PDF文件

    支持的格式：
    - 图片：JPG, JPEG, PNG, BMP, WebP, TIFF, TIF
    - 文档：PDF（会自动渲染为图片）
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请选择至少一个文件"
        )

    upload_dir = get_user_upload_dir(current_user.id)
    results = []

    for file in files:
        # 验证文件类型
        if not validate_file(file):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件格式: {file.filename}"
            )

        # 读取文件内容
        content = await file.read()

        # 验证文件大小
        if len(content) > settings.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件过大: {file.filename}，最大支持10MB"
            )

        # 生成唯一文件名
        ext = os.path.splitext(file.filename)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(upload_dir, unique_filename)

        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)

        # 判断是否为PDF文件
        if is_pdf_file(file.filename):
            # 处理PDF文件：渲染每一页为图片
            try:
                from services.pdf_service import render_pdf_pages

                # 渲染PDF页面
                pdf_items = render_pdf_pages(file_path, upload_dir)

                # 为每一页创建数据库记录
                for item in pdf_items:
                    result = OCRResult(
                        user_id=current_user.id,
                        task_id=0,  # 临时任务ID，后续创建任务时更新
                        image_path=item["file_path"],
                        image_name=item["file_name"],
                        status="uploaded"
                    )
                    db.add(result)
                    results.append(result)

                logger.info("PDF %s rendered to %d pages", file.filename, len(pdf_items))

            except Exception as e:
                logger.error("Failed to process PDF %s: %s", file.filename, e)
                # 删除已保存的PDF文件
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"PDF处理失败: {str(e)}"
                )
        else:
            # 处理图片文件
            result = OCRResult(
                user_id=current_user.id,
                task_id=0,  # 临时任务ID，后续创建任务时更新
                image_path=file_path,
                image_name=file.filename,
                status="uploaded"
            )
            db.add(result)
            results.append(result)

    db.commit()

    # 刷新获取ID
    for result in results:
        db.refresh(result)

    return results


@router.get("/images", response_model=ResultListResponse, summary="获取已上传图片列表")
async def get_uploaded_images(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户上传的图片列表"""
    results = db.query(OCRResult).filter(
        OCRResult.user_id == current_user.id,
        OCRResult.task_id == 0  # 未关联任务的图片
    ).order_by(OCRResult.created_at.desc()).all()

    return {"results": results, "total": len(results)}


@router.delete("/images/{image_id}", summary="删除已上传图片")
async def delete_uploaded_image(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除指定的已上传图片"""
    result = db.query(OCRResult).filter(
        OCRResult.id == image_id,
        OCRResult.user_id == current_user.id
    ).first()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="图片不存在"
        )

    # 删除文件
    if os.path.exists(result.image_path):
        os.remove(result.image_path)

    # 删除数据库记录
    db.delete(result)
    db.commit()

    return {"message": "删除成功"}
