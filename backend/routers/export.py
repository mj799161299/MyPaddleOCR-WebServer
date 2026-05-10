"""
导出路由模块
============
提供 OCR 识别结果的导出功能，支持多种格式的单页下载和合并下载。

导出流水线概述：
---------------
1. 【单页导出】 POST /api/export/download
   选择单个结果，清洗 Markdown 内容（移除无效图片、修正路径、清理公式空格），
   按指定格式（markdown / json / html）生成临时文件并返回 FileResponse 下载。

2. 【合并导出】 POST /api/export/merge
   选择多个结果，按传入顺序合并所有 markdown 内容（以 "---" 分隔），
   同时将关联的 PaddleOCR 提取图片或源图片复制到 ZIP 中，
   修正所有图片引用路径为相对路径，最终打包为 ZIP 文件下载。

Markdown 内容清洗流程：
-----------------------
1. 图片路径处理：
   - 优先使用 PaddleOCR 提取的图片（位于 uploads/{user_id}/imgs/{result_id}/）
   - 将提取图片复制到临时目录的 imgs/ 子目录，前缀编号（extracted_001_xxx）
   - 使用正则替换 Markdown 中的图片引用为相对路径
   - 若无提取图片，回退使用源图片（整页渲染），前缀编号（source_001_xxx）
   - 若源图片也不存在，删除所有 <img> 标签

2. LaTeX 公式清洗：
   - 行间公式：去除 "$$ ... $$" 内部的头尾空格（$$ x=y $$ → $$x=y$$）
   - 行内公式：去除 "$ ... $" 内部的头尾空格（$ x=y $ → $x=y$）
   - 使用正则后向否定断言 (?<!\$) 区分行内公式与货币符号

文件组织：
---------
- 临时目录：exports/{user_id}/{export_id}/（导出完成后自动清理）
- ZIP 包内结构：
  ├── ocr_result.{md|json|html}   # 合并后的主文件
  └── imgs/                        # 图片目录
      ├── extracted_001_xxx.png    # PaddleOCR 提取的图片
      └── source_001_xxx.png       # 源图片（回退方案）
"""

import os
import re
import uuid
import zipfile
import shutil
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from models.result import OCRResult
from schemas.result import ExportRequest
from utils.security import get_current_user
from services.ocr_service import ExportService
from config import settings

router = APIRouter(prefix="/api/export", tags=["导出"])
logger = logging.getLogger(__name__)


def get_user_export_dir(user_id: int) -> str:
    """
    获取用户的导出临时目录路径
    ===========================
    用途：根据用户ID创建/返回导出临时目录，所有导出操作的临时文件在此目录下生成。
    目录结构：{EXPORT_DIR}/{user_id}/
    
    参数：
        user_id (int)：用户ID
    
    返回值：
        str：用户专属导出目录的绝对路径
    
    边界处理：
        - 目录不存在时自动创建（exist_ok=True）
    """
    user_dir = os.path.join(settings.EXPORT_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def _get_user_result_images_dir(user_id: int, result_id: int) -> str:
    """
    获取单个结果的 PaddleOCR 提取图片存储目录
    ==========================================
    用途：定位 OCR 识别过程中 PaddleOCR 提取的子图片存储位置。
    PaddleOCR 在识别时会将文档中的图片、表格等元素提取为独立图片保存在此目录。
    
    目录结构：{UPLOAD_DIR}/{user_id}/imgs/{result_id}/
    
    参数：
        user_id (int)：用户ID
        result_id (int)：OCR结果ID
    
    返回值：
        str：提取图片目录的绝对路径
    
    边界处理：
        - 目录不存在时自动创建（exist_ok=True）
    """
    d = os.path.join(settings.UPLOAD_DIR, str(user_id), "imgs", str(result_id))
    os.makedirs(d, exist_ok=True)
    return d


@router.post("/download", summary="下载当前页")
async def export_single(
    export_data: ExportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    下载当前页（单结果导出）
    ========================
    用途：将当前选中的单个 OCR 结果按指定格式导出为可下载文件。
    
    导出流水线：
        1. 验证结果归属和状态（必须属于当前用户且已完成）
        2. Markdown 清洗（图片路径修复 + 公式空格清理，详见模块文档注释）
        3. 根据 format 参数调用 ExportService 生成对应格式文件
        4. 返回 FileResponse 直接下载
    
    输入参数：
        export_data (ExportRequest)：
            - result_ids (List[int])：结果ID列表（此处仅使用第一个）
            - format (str)：导出格式，支持 "markdown" / "json" / "html"
    
    返回值：
        FileResponse：可直接下载的文件响应
            - Content-Type 根据格式自动设置（text/markdown, application/json, text/html）
            - 文件名格式：ocr_result.{ext}
    
    权限要求：
        需要登录，只能导出自己的已完成结果。
    
    边界情况 / 错误处理：
        - 400：没有可导出的结果（result_ids 为空或不存在已完成的结果）
        - 400：不支持的导出格式（不在 [markdown, json, html] 中）
        - 500：导出过程中文件操作异常（自动清理临时目录）
        - 图片路径处理：
          * 源图片存在 → 将 <img> 标签的 src 替换为纯文件名
          * 源图片不存在 → 删除所有 <img> 标签（避免 Markdown 渲染器报 404）
    """
    # 查询属于当前用户且已完成的 OCR 结果
    results = db.query(OCRResult).filter(
        OCRResult.id.in_(export_data.result_ids),
        OCRResult.user_id == current_user.id,
        OCRResult.status == "completed"
    ).all()

    if not results:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有可导出的结果")

    result = results[0]

    # ---- Markdown 清洗阶段 ----

    # 清洗 Markdown：清除无效图片、修正图片路径、清理公式空格
    md_text = result.markdown_text or ""

    # 步骤1：图片路径处理
    # 如果源图片文件存在，将 <img> 标签的 src 替换为纯文件名（相对路径，方便本地查看）
    if os.path.isfile(result.image_path):
        src_name = os.path.basename(result.image_path)
        md_text = re.sub(r'<img\s+[^>]*src\s*=\s*["\x27][^"\x27]*["\x27][^>]*/?>',
                        f'<img src="{src_name}" alt="Image" />', md_text, flags=re.IGNORECASE)
    else:
        # 源图片不存在：删除所有 <img> 标签，避免 Markdown 渲染器尝试加载不存在的图片
        md_text = re.sub(r'<img\s+[^>]*/?>\s*', '', md_text, flags=re.IGNORECASE)

    # 步骤1.5：包裹裸 LaTeX 标记
    # PaddleOCR-VL 在 HTML 表格 <td> 中输出 _{}、^{}、\command 等不带 $ 定界符的 LaTeX
    def _wrap_latex_single(m):
        content = m.group(2)
        if not content.strip() or '$' in content:
            return m.group(0)
        return m.group(1) + '$' + content.strip() + '$' + m.group(3)
    md_text = re.sub(r'(>)([^<]*?[_^{}\\\]{1,3}[^<]*?)(<)', _wrap_latex_single, md_text)

    # 步骤2：LaTeX 公式清洗
    # 去除行间公式 $$ ... $$ 内部的头尾空格，确保渲染正确
    # 使用 DOTALL 标志使 . 也能匹配换行符（多行公式场景）
    md_text = re.sub(r"\$\$\s*(.+?)\s*\$\$", r"$$\1$$", md_text, flags=re.DOTALL)
    # 去除行内公式 $ ... $ 内部的头尾空格
    # (?<!\$) 后向否定断言：确保 $ 前面没有另一个 $（区分行内公式与行间公式）
    # (?!\$)  前向否定断言：确保 $ 后面没有另一个 $
    md_text = re.sub(r"(?<!\$)\$\s*(.+?)\s*\$(?!\$)", r"$\1$", md_text)
    # 步骤2.5：剥离非法 LaTeX 内容的 $ 定界符
    # PaddleOCR-VL 会将 ##标题、&lt;实体等内容误包进 $，导致 KaTeX 报错
    md_text = re.sub(r"(?<!\$)\$\s*([^$]*[#&][^$]*)\s*\$(?!\$)", r"\1", md_text)

    # ---- 清洗结束，构建导出数据 ----

    export_results = [{
        "image_name": result.image_name,
        "markdown_text": md_text,
        "json_data": result.json_data,
    }]

    # ---- 生成导出文件 ----

    export_dir = get_user_export_dir(current_user.id)
    export_id = uuid.uuid4().hex[:8]
    temp_dir = os.path.join(export_dir, export_id)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        format_type = export_data.format.lower()
        ext_map = {"markdown": "md", "json": "json", "html": "html"}
        ext = ext_map.get(format_type, format_type)

        if format_type == "markdown":
            output_file = os.path.join(temp_dir, f"ocr_result.{ext}")
            ExportService.export_markdown(export_results, output_file)
        elif format_type == "json":
            output_file = os.path.join(temp_dir, f"ocr_result.{ext}")
            ExportService.export_json(export_results, output_file)
        elif format_type == "html":
            output_file = os.path.join(temp_dir, f"ocr_result.{ext}")
            ExportService.export_html(export_results, output_file)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"不支持的格式: {format_type}")

        # 返回文件下载响应，Content-Type 根据格式自动设置
        return FileResponse(
            path=output_file,
            media_type={"markdown": "text/markdown", "json": "application/json", "html": "text/html"}[format_type],
            filename=f"ocr_result.{ext}"
        )
    except HTTPException:
        # HTTP 异常直接向上抛出，不做额外处理
        raise
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        # 导出失败时清理临时目录，避免残留文件占用磁盘
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.post("/merge", summary="整合下载（合并所有结果+图片打包ZIP）")
async def export_merge(
    export_data: ExportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    整合下载（合并所有结果+图片打包ZIP）
    ===================================
    用途：将多个选中的 OCR 结果按传入顺序合并为一个文件，同时将所有关联图片打包进 ZIP 下载。
    
    导出流水线（合并模式）：
        1. 查询所有属于当前用户且已完成的结果
        2. 按传入的 result_ids 顺序排列结果（保持前端选择顺序）
        3. 逐个处理每个结果：
           a. 优先尝试 PaddleOCR 提取图片（_get_user_result_images_dir）
              - 若存在提取图片 → 复制到 imgs/ 目录，路径前缀 extracted_{序号}_
              - 替换 Markdown 中的图片引用为 imgs/extracted_xxx 相对路径
           b. 若无提取图片 → 回退使用源图片
              - 若源图片存在 → 复制到 imgs/ 目录，路径前缀 source_{序号}_
              - 替换 Markdown 中的图片引用为 imgs/source_xxx 相对路径
              - 若源图片也不存在 → 删除 <img> 标签
           c. LaTeX 公式空格清洗（同单页导出）
        4. 合并所有 Markdown 内容（以 "\n\n---\n\n" 分隔）
        5. 按指定格式生成文件 + 打包 imgs/ 目录为 ZIP
        6. 返回 ZIP FileResponse，临时目录在 finally 中自动清理
    
    输入参数：
        export_data (ExportRequest)：
            - result_ids (List[int])：结果ID列表（保持前端选择顺序）
            - format (str)：导出格式，支持 "markdown" / "json" / "html"
    
    返回值：
        FileResponse：ZIP 文件下载响应
            - Content-Type：application/zip
            - 文件名：ocr_results_{export_id}.zip
    
    权限要求：
        需要登录，只能导出自己的已完成结果。
    
    边界情况 / 错误处理：
        - 400：没有可导出的结果（result_ids 为空或无已完成的结果）
        - 400：不支持的导出格式
        - 500：文件操作异常（自动清理临时目录）
        - 图片去重：使用 copied_images set 避免同一图片被多次复制
        - 编号前缀：
          * extracted_{idx+1:03d}_xxx.png —— PaddleOCR 提取的子图，编号从 001 开始
          * source_{idx+1:03d}_xxx.png  —— 源图片（整页），编号从 001 开始
        - 路径替换正则：
          * 提取图片：按原始文件名精确匹配并替换（re.escape 防正则注入）
          * 源图片：替换所有 <img> 标签的 src 属性
        - finally 块：无论导出成功或失败，临时目录都会被删除
    """
    # 查询属于当前用户且已完成的结果
    results = db.query(OCRResult).filter(
        OCRResult.id.in_(export_data.result_ids),
        OCRResult.user_id == current_user.id,
        OCRResult.status == "completed"
    ).all()

    if not results:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有可导出的结果")

    # 按传入顺序排列
    # 构建 id → 序号映射，确保结果按前端选择的顺序导出
    id_order = {rid: i for i, rid in enumerate(export_data.result_ids)}
    results.sort(key=lambda r: id_order.get(r.id, 999))

    export_dir = get_user_export_dir(current_user.id)
    export_id = uuid.uuid4().hex[:8]
    temp_dir = os.path.join(export_dir, export_id)
    os.makedirs(temp_dir, exist_ok=True)

    try:
        format_type = export_data.format.lower()
        ext = {"markdown": "md", "json": "json", "html": "html"}.get(format_type, format_type)
        merged_content_parts = []
        all_json = []
        copied_images = set()  # 图片去重集合，避免重复复制

        for idx, result in enumerate(results):
            md_text = result.markdown_text or ""

            # ---- 阶段1：查找 PaddleOCR 提取的图片 ----
            # PaddleOCR 在识别时会将文档中的子图提取到 {UPLOAD_DIR}/{user_id}/imgs/{result_id}/
            result_imgs_dir = _get_user_result_images_dir(current_user.id, result.id)
            has_extracted_images = False

            if os.path.isdir(result_imgs_dir):
                imgs_list = [f for f in os.listdir(result_imgs_dir) if os.path.isfile(os.path.join(result_imgs_dir, f))]
                if imgs_list:
                    has_extracted_images = True
                    imgs_dir = os.path.join(temp_dir, "imgs")
                    os.makedirs(imgs_dir, exist_ok=True)
                    for img_file in imgs_list:
                        # 命名规则：extracted_{序号三位数}_{原始文件名}
                        dst_name = f"extracted_{idx+1:03d}_{img_file}"
                        shutil.copy2(
                            os.path.join(result_imgs_dir, img_file),
                            os.path.join(imgs_dir, dst_name)
                        )
                        # 替换 PaddleOCR 的图片引用：将 Markdown 中引用原始文件名的路径替换为 imgs/ 相对路径
                        # re.escape 防止文件名中的特殊字符（如 .）被当作正则符号
                        escaped_name = re.escape(img_file)
                        md_text = re.sub(
                            rf'(<img\s+[^>]*src\s*=\s*["\x27])[^"\x27]*{escaped_name}(["\x27])',
                            rf'\1imgs/{dst_name}\2',
                            md_text,
                            flags=re.IGNORECASE
                        )

            # ---- 阶段2：无提取图片时的回退 ----
            # 回退：使用源图片（整页渲染），这是 PaddleOCR 输入的原始页面图片
            if not has_extracted_images:
                imgs_dir = os.path.join(temp_dir, "imgs")
                os.makedirs(imgs_dir, exist_ok=True)
                if os.path.isfile(result.image_path):
                    # 命名规则：source_{序号三位数}_{原始文件名}
                    source_dst = f"source_{idx+1:03d}_{os.path.basename(result.image_path)}"
                    shutil.copy2(result.image_path, os.path.join(imgs_dir, source_dst))
                    # 替换所有 <img> 标签的 src 为回退图片的相对路径
                    md_text = re.sub(
                        r'<img\s+[^>]*src\s*=\s*["\x27][^"\x27]*["\x27]',
                        f'<img src="imgs/{source_dst}"',
                        md_text,
                        flags=re.IGNORECASE
                    )
                else:
                    # 连源图片都不存在：删除所有 <img> 标签，避免损坏的图片引用
                    md_text = re.sub(r'<img\s+[^>]*/?>\s*', '', md_text, flags=re.IGNORECASE)

            # ---- 阶段2.5：包裹裸 LaTeX 标记 ----
            # 同单结果导出，处理 PaddleOCR-VL 在表格中输出的不带 $ 的 LaTeX
            def _wrap_latex_merge(m):
                content = m.group(2)
                if not content.strip() or '$' in content:
                    return m.group(0)
                return m.group(1) + '$' + content.strip() + '$' + m.group(3)
            md_text = re.sub(r'(>)([^<]*?[_^{}\\\]{1,3}[^<]*?)(<)', _wrap_latex_merge, md_text)

            # ---- 阶段3：LaTeX 公式空格清洗 ----
            # 清洗 LaTeX 公式多余空格：$ x=y $ → $x=y$，确保公式渲染正确
            md_text = re.sub(r"\$\$\s*(.+?)\s*\$\$", r"$$\1$$", md_text, flags=re.DOTALL)
            md_text = re.sub(r"(?<!\$)\$\s*(.+?)\s*\$(?!\$)", r"$\1$", md_text)
            # 剥离含 # & 的行内公式定界符
            md_text = re.sub(r"(?<!\$)\$\s*([^$]*[#&][^$]*)\s*\$(?!\$)", r"\1", md_text)

            # ---- 阶段4：按格式收集内容 ----
            if format_type == "json":
                all_json.append({
                    "image_name": result.image_name,
                    "markdown_text": md_text,
                    "json_data": result.json_data,
                })
            else:
                merged_content_parts.append(md_text)

        # ---- 生成主文件 ----

        output_file = os.path.join(temp_dir, f"ocr_result.{ext}")

        if format_type == "markdown":
            # Markdown 合并：以 "---" 水平分隔线连接各结果
            content = "\n\n---\n\n".join(merged_content_parts)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(content)
        elif format_type == "json":
            # JSON 格式：所有结果组装为数组，保留结构化数据
            with open(output_file, "w", encoding="utf-8") as f:
                import json
                json.dump(all_json, f, ensure_ascii=False, indent=2)
        elif format_type == "html":
            # HTML 格式：通过 ExportService 生成带样式的 HTML
            ExportService.export_html(
                [{"image_name": results[i].image_name, "markdown_text": merged_content_parts[i]}
                 for i in range(len(results))],
                output_file
            )

        # ---- 阶段5：打包为 ZIP ----
        # 打包为ZIP（包含合并结果文件 + 所有图片）
        # ZIP_DEFLATED 使用压缩算法减小文件体积
        zip_path = os.path.join(export_dir, f"ocr_results_{export_id}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # 使用相对路径作为 ZIP 内的路径，保持目录结构
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=f"ocr_results_{export_id}.zip"
        )
    except HTTPException:
        # HTTP 异常直接向上抛出
        raise
    except Exception as e:
        logger.error(f"Merge export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")
    finally:
        # 无论成功失败，清理临时目录
        # 注意：ZIP 文件已保存到 export_dir 父目录，不会被清理
        shutil.rmtree(temp_dir, ignore_errors=True)
