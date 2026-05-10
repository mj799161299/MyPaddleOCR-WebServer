"""
PDFService — PDF 页面渲染服务（Web版）

参考原项目 src/services/pdf_service.py 的实现，适配 Web 服务器环境。

使用 pypdfium2（Chromium PDF 引擎）进行渲染，200 DPI 输出，
确保 OCR 识别质量。

数据流：
  PDF 文件路径 → pypdfium2.PdfDocument → 逐页渲染 → PIL Image → 临时 PNG
  → 保存到用户上传目录，创建 OCRResult 记录

注意事项：
  - 渲染出的临时 PNG 文件保存在用户上传目录
  - 每个页面对应一个独立的 OCRResult 记录
"""
import os
import logging
import tempfile
from typing import List

from PIL import Image

logger = logging.getLogger(__name__)

# PDF 渲染 DPI，200 DPI 在质量和性能间取得平衡
DPI = 200


def render_pdf_pages(pdf_path: str, output_dir: str) -> List[dict]:
    """将 PDF 文件的所有页面渲染为 PNG 图片。

    控制流：
      1. pypdfium2 打开 PDF 文档
      2. 遍历每一页：
         a. page.render(scale=DPI/72) → 渲染为位图
         b. bitmap.to_pil() → 转为 PIL Image
         c. 保存到 output_dir
      3. 返回每页的文件信息列表

    Args:
        pdf_path: PDF 文件的绝对路径
        output_dir: 输出目录

    Returns:
        list[dict] — 每个页面对应一个 dict，包含 file_path, page_number
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise RuntimeError("pypdfium2未安装，请运行: pip install pypdfium2")

    items = []

    try:
        pdf = pdfium.PdfDocument(pdf_path)
    except Exception as e:
        logger.error("Failed to open PDF %s: %s", pdf_path, e)
        raise RuntimeError(f"无法打开PDF文件: {e}")

    page_count = len(pdf)
    if page_count == 0:
        logger.warning("PDF has no pages: %s", pdf_path)
        return items

    # pypdfium2 的 scale 是相对于 72 DPI 的缩放倍数
    scale = DPI / 72.0
    logger.info("Rendering PDF %s (%d pages, scale=%.2f)", pdf_path, page_count, scale)

    os.makedirs(output_dir, exist_ok=True)

    for page_idx in range(page_count):
        try:
            page = pdf[page_idx]
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()

            # 生成输出文件名
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            output_filename = f"{base_name}_page_{page_idx + 1:03d}.png"
            output_path = os.path.join(output_dir, output_filename)

            pil_image.save(output_path, "PNG")

            items.append({
                "file_path": output_path,
                "file_name": f"{base_name} (第{page_idx + 1}页)",
                "page_number": page_idx + 1,
                "source_pdf": pdf_path,
            })

            logger.info("Rendered page %d/%d of %s", page_idx + 1, page_count, os.path.basename(pdf_path))

        except Exception as e:
            logger.error("Failed to render page %d of %s: %s", page_idx + 1, pdf_path, e)
            # 继续处理其他页面

    return items
