"""
OCRService — PaddleOCRVL SDK 封装（Web版）

参考原项目 src/services/ocr_service.py 的实现，适配 Web 服务器环境。

架构：
  - 全局单例：_global_pipeline 在首次请求时创建，后续请求复用
  - 通过 llama-cpp-server 调用 PaddleOCR-VL-1.5 模型
  - 返回 Markdown 文本、JSON 原始数据
  - 支持重试机制（最多3次）

调用时序：
  1. OCRService(server_url)          # 创建服务实例（不初始化 pipeline）
  2. service.recognize(image_path)    # 首次调用时初始化 pipeline，然后识别
  3. 返回 {"markdown_text", "json_data"}
"""
import os
import logging
import time
import traceback
import re
import json
import shutil
import threading
import requests
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# 全局单例管道，避免重复初始化
_global_pipeline = None
_pipeline_server_url = None
_pipeline_lock = threading.Lock()


class OCRService:
    """PaddleOCRVL 识别服务（Web版）。

    通过 llama-cpp-server 后端调用 PaddleOCR-VL-1.5 视觉语言模型，
    支持单张图片的文本识别，返回 Markdown 和 JSON 格式结果。
    """

    def __init__(self, server_url: str = None):
        """创建服务实例。

        Args:
            server_url: llama-cpp-server 地址，如 "http://127.0.0.1:7950/v1"
        """
        self._server_url = (server_url or settings.OCR_SERVER_URL).rstrip("/")

    def _get_pipeline(self):
        """获取 PaddleOCRVL 管道（全局单例，带重试，线程安全）。

        首次调用时创建 pipeline 并缓存到 _global_pipeline，后续调用直接返回。
        使用 threading.Lock 防止多线程同时初始化导致 GPU 资源竞争。
        """
        global _global_pipeline, _pipeline_server_url

        # 快速路径：命中缓存且 server_url 一致（无需加锁）
        if _global_pipeline is not None and _pipeline_server_url == self._server_url:
            return _global_pipeline

        with _pipeline_lock:
            # 双重检查：可能另一个线程已经初始化完毕
            if _global_pipeline is not None and _pipeline_server_url == self._server_url:
                return _global_pipeline

            logger.info("Initializing PaddleOCRVL pipeline, server_url=%s", self._server_url)

        last_err = None
        for attempt in range(3):
            try:
                from paddleocr import PaddleOCRVL
                _global_pipeline = PaddleOCRVL(
                    vl_rec_backend="llama-cpp-server",
                    vl_rec_server_url=self._server_url,
                )
                _pipeline_server_url = self._server_url
                logger.info("PaddleOCRVL pipeline initialized successfully (attempt %d)", attempt + 1)
                return _global_pipeline
            except ImportError:
                raise RuntimeError("paddleocr未安装，请运行: pip install paddleocr")
            except Exception as e:
                last_err = e
                tb = traceback.format_exc()
                logger.warning(
                    "PaddleOCRVL pipeline creation attempt %d/3 failed: %s\n%s",
                    attempt + 1, e, tb
                )
                if attempt < 2:
                    time.sleep(3)

        raise RuntimeError(f"PaddleOCRVL管道创建失败(重试3次): {last_err}")

    def recognize(self, image_path: str, save_images_dir: str = None) -> dict:
        """识别单张图片。"""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片文件不存在: {image_path}")

        logger.info("Recognizing: %s", image_path)
        pipeline = self._get_pipeline()
        outputs = pipeline.predict(image_path)

        result = None
        for res in outputs:
            result = res
            break

        if result is None:
            raise RuntimeError(f"OCR未返回结果: {image_path}")

        md_text = ""
        md_data = getattr(result, "markdown", None)
        if isinstance(md_data, dict):
            md_text = md_data.get("markdown_texts", "") or md_data.get("markdown_text", "") or ""
        elif isinstance(md_data, str):
            md_text = md_data

        json_data = {}
        if hasattr(result, "json") and result.json:
            json_data = result.json if isinstance(result.json, dict) else {}
        elif hasattr(result, "__dict__"):
            json_data = {
                k: v for k, v in result.__dict__.items()
                if k not in ("markdown",) and not k.startswith("_")
                and isinstance(v, (str, int, float, dict, list, type(None)))
            }

        # 提取嵌入图片
        saved_count = 0
        if save_images_dir:
            saved_count = self._save_result_images(result, save_images_dir, md_text)

        logger.info("Recognized %s: markdown_len=%d, images_saved=%d", os.path.basename(image_path), len(md_text), saved_count)
        return {"markdown_text": md_text, "json_data": json_data, "images_saved": saved_count}

    def _save_result_images(self, result, save_dir: str, md_text: str = "") -> int:
        """从 OCR 结果中提取并保存嵌入图片。
        
        尝试多种方式：
        1. 调用 result.save_to_markdown() 提取图片
        2. 从 result.images 属性读取 PIL Image
        3. 查找当前工作目录下的 imgs/ 目录
        """
        import tempfile
        saved_count = 0
        os.makedirs(save_dir, exist_ok=True)

        # 方式1: save_to_markdown
        try:
            tmpdir = tempfile.mkdtemp(prefix="paddleocr_imgs_")
            try:
                result.save_to_markdown(tmpdir)
                tmp_imgs = os.path.join(tmpdir, "imgs")
                if os.path.isdir(tmp_imgs):
                    for fname in os.listdir(tmp_imgs):
                        src = os.path.join(tmp_imgs, fname)
                        if os.path.isfile(src):
                            shutil.copy2(src, os.path.join(save_dir, fname))
                            saved_count += 1
                if saved_count > 0:
                    logger.info("save_to_markdown extracted %d images for %s", saved_count, save_dir)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            logger.debug("save_to_markdown image extraction failed: %s", e)

        # 方式2: result.images 属性
        if saved_count == 0 and hasattr(result, 'images'):
            try:
                images = result.images
                if images:
                    for i, img in enumerate(images):
                        if hasattr(img, 'save'):
                            fname = f"image_{i+1:03d}.png"
                            img.save(os.path.join(save_dir, fname))
                            saved_count += 1
                    if saved_count > 0:
                        logger.info("result.images extracted %d images", saved_count)
            except Exception as e:
                logger.debug("result.images extraction failed: %s", e)

        # 方式3: 查找 CWD 下的 imgs/ 目录
        if saved_count == 0:
            try:
                cwd_imgs = os.path.join(os.getcwd(), "imgs")
                if os.path.isdir(cwd_imgs):
                    for fname in os.listdir(cwd_imgs):
                        src = os.path.join(cwd_imgs, fname)
                        if os.path.isfile(src):
                            shutil.copy2(src, os.path.join(save_dir, fname))
                            saved_count += 1
                    if saved_count > 0:
                        logger.info("cwd/imgs/ found %d images", saved_count)
            except Exception as e:
                logger.debug("cwd/imgs/ scan failed: %s", e)

        return saved_count

    @staticmethod
    def check_server(server_url: str = None) -> dict:
        """检查OCR服务器状态。

        Args:
            server_url: llama-cpp-server 地址

        Returns:
            {"status": "online"|"offline"|"error", "message": str}
        """
        url = (server_url or settings.OCR_SERVER_URL).rstrip("/") + "/models"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return {"status": "online", "message": "OCR服务正常"}
            return {"status": "error", "message": f"服务返回状态码: {resp.status_code}"}
        except requests.ConnectionError:
            return {"status": "offline", "message": "无法连接到OCR服务"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


def _wrap_bare_latex(text: str) -> str:
    """包裹裸 LaTeX 标记：将 _{...} 或 ^{...} 等不带 $ 定界符的 LaTeX 下标/上标加上 $。
    
    PaddleOCR-VL 在表格中输出 V_{FC}、k_{SVR}、c^{2} 等不带 $ 的 LaTeX，
    此函数将其包裹为 $...$ 以便后续公式处理流程识别。
    
    正则限制：匹配 [字母或反斜杠][可选字母数字]_或^{花括号内容}，
    避免误包 CSS（text_align）和普通文字。
    """
    saved = []
    text = re.sub(r'\$[^$]+\$', lambda m: (saved.append(m.group(0)), f"__Y{len(saved) - 1}__")[1], text)
    text = re.sub(r'([A-Za-z\\][A-Za-z0-9]*)([_^]\{[^}]+\})', r'$\1\2$', text)
    for i, s in enumerate(saved):
        text = text.replace(f"__Y{i}__", s)
    return text


def _wrap_display_formulas(text: str) -> str:
    """检测裸 display 公式（\\frac、\\left 等不在 $$ 内）并包裹 $$...$$。

    在 _md_to_html() 中用于 HTML/Word 导出，
    同时在 export.py 中用于 Markdown 导出。
    
    处理两种情况：
    1. 整行无 $$ — 去除行内 $ 定界符后整行包裹 $$
    2. 行内混合 $$ 块和裸公式 — 保护已有 $$ 块，逐段检测并包裹裸公式
    """
    _TRIGGERS = ('\\frac', '\\int', '\\sum', '\\prod', '\\sqrt', '\\begin', '\\binom',
                 '\\mathrm', '\\mathsf', '\\textrm', '\\text', '\\left', '\\right')
    # 无论是否含触发命令，始终拆分同行 $$ $$ 序列
    text = re.sub(r'\$\$\s+\$\$', '$$\n\n$$', text)
    if not any(cmd in text for cmd in _TRIGGERS):
        return text
    lines = text.split('\n')
    result_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('<') or stripped.startswith('```'):
            result_lines.append(line)
            continue
        if not any(cmd in stripped for cmd in _TRIGGERS):
            result_lines.append(line)
            continue
        if '$$' not in stripped:
            cleaned = re.sub(r'\$([^$]+)\$', r'\1', stripped)
            result_lines.append(f'$${cleaned.strip()}$$')
            continue
        protected = []
        def _protect(m):
            protected.append(m.group(0))
            return f'\x00P{len(protected) - 1}\x00'
        temp = re.sub(r'\$\$([\s\S]*?)\$\$', _protect, stripped)
        temp = temp.replace('$$', '')
        temp = re.sub(r'\$([^$]+)\$', r'\1', temp)
        parts = re.split(r'(\x00P\d+\x00)', temp)
        for j, part in enumerate(parts):
            if re.match(r'\x00P\d+\x00', part):
                continue
            part_stripped = part.strip()
            if part_stripped and any(cmd in part_stripped for cmd in _TRIGGERS):
                parts[j] = f' $${part_stripped}$$ '
        new_line = ''.join(parts).strip()
        for k, p in enumerate(protected):
            new_line = new_line.replace(f'\x00P{k}\x00', p)
        result_lines.append(new_line)
    text = '\n'.join(result_lines)
    text = re.sub(r'\$\$\s+\$\$', '$$\n\n$$', text)
    return text


class ExportService:
    """导出服务 - 复用自原项目"""

    @staticmethod
    def export_markdown(results: list, output_path: str):
        """导出为Markdown格式"""
        parts = []
        for result in results:
            if result.get("markdown_text"):
                parts.append(result["markdown_text"])

        content = "\n\n---\n\n".join(parts)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path

    @staticmethod
    def export_json(results: list, output_path: str):
        """导出为JSON格式"""
        export_data = []
        for result in results:
            export_data.append({
                "image_name": result.get("image_name", ""),
                "markdown_text": result.get("markdown_text", ""),
                "json_data": result.get("json_data", {}),
            })

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        return output_path

    @staticmethod
    def export_html(results: list, output_path: str, wrap_bare: bool = True):
        """导出为HTML格式（带KaTeX数学公式支持）"""
        HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OCR 扫描结果</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<script>
    document.addEventListener("DOMContentLoaded", function() {{
        renderMathInElement(document.body, {{
            delimiters: [
                {{left: "\\\\(", right: "\\\\)", display: false}},
                {{left: "\\\\[", right: "\\\\]", display: true}}
            ],
            throwOnError: false
        }});
    }});
</script>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 20px;
    line-height: 1.6;
    color: #333;
    background: #fff;
}}
h1, h2, h3, h4, h5, h6 {{ margin-top: 1.5em; margin-bottom: 0.5em; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background-color: #f5f5f5; }}
code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
pre {{ background: #f4f4f4; padding: 12px; border-radius: 5px; overflow-x: auto; }}
img {{ max-width: 100%; }}
hr {{ border: none; border-top: 1px solid #ddd; margin: 2em 0; }}
.item {{ margin-bottom: 2em; }}
.item-title {{ color: #666; font-size: 0.9em; margin-bottom: 0.5em; }}
</style>
</head>
<body>
<h1>OCR 扫描结果</h1>
{body}
</body>
</html>"""

        parts = []
        for idx, result in enumerate(results):
            name = result.get("image_name", f"图片 {idx + 1}")
            md_text = result.get("markdown_text", "")
            html_body = ExportService._md_to_html(md_text, wrap_bare=wrap_bare)
            parts.append(f'<div class="item"><div class="item-title">{name}</div>\n{html_body}</div>')

        body = "\n<hr/>\n".join(parts)
        html_content = HTML_TEMPLATE.format(body=body)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path

    @staticmethod
    def export_word(results: list, output_path: str, image_dir: str = None):
        """使用 pandoc 将 Markdown 转换为 Word (.docx) 格式。
        
        流水线：_md_to_html() 生成干净 HTML（表格/公式/图片已就绪）
              → pandoc 单次 HTML→DOCX 转换
        """
        import subprocess
        import tempfile
        from fastapi import HTTPException

        if not shutil.which('pandoc'):
            raise HTTPException(status_code=501, detail="Word 导出需要 pandoc，请安装 pandoc 后重试")

        # 用 _md_to_html() 生成干净 HTML（wrap_bare=False，裸 LaTeX 已在 export.py 中包裹过）
        parts = []
        for idx, result in enumerate(results):
            md_text = result.get("markdown_text", "")
            page_name = result.get("image_name", f"第 {idx + 1} 页")
            html_body = ExportService._md_to_html(md_text, wrap_bare=False)
            parts.append(f'<!-- page {idx + 1}: {page_name} -->\n{html_body}')

        body = "\n<div style=\"page-break-after: always;\"></div>\n".join(parts)

        # 清洗 \(...\) 和 \[...\] 内部头尾空格（pandoc OMML 对空格敏感）
        body = re.sub(r'\\\(\s+', r'\\(', body)
        body = re.sub(r'\s+\\\)', r'\\)', body)
        body = re.sub(r'\\\[\s+', r'\\[', body)
        body = re.sub(r'\s+\\\]', r'\\]', body)

        # pandoc HTML reader 不认 \(...\)，转回 $...$ / $$...$$
        body = body.replace('\\(', '$').replace('\\)', '$')
        body = body.replace('\\[', '$$').replace('\\]', '$$')

        # pandoc LaTeX parser 不认 \degree，替换为标准 LaTeX
        body = body.replace('\\degree', '^{\\circ}')

        # 合并 border style 到已有 style 属性（避免重复 style=""）
        # PaddleOCR 表格已有 style='margin:auto;word-wrap:break-word;'
        # 需将 border 追加到已有 style 中，而非新增第二个 style 属性
        border_css = 'border:1px solid black;border-collapse:collapse'
        def _merge_table_style(m):
            prefix = m.group(1)
            style_val = m.group(2)
            suffix = m.group(3)
            merged = style_val.rstrip('; ') + ';' + border_css
            return f'{prefix} style="{merged}"{suffix}'
        body = re.sub(r'(<table\b[^>]*?)style=[\'"]([^\'"]*?)[\'"]([^>]*>)', _merge_table_style, body)
        # 也处理没有 style 属性的 <table> 标签
        body = re.sub(r'(<table\b)(?![^>]*style=)([^>]*)(>)', r'\1\2 style="border:1px solid black;border-collapse:collapse"\3', body)

        HTML = """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>table, th, td {{ border: 1px solid black; border-collapse: collapse; padding: 4px 8px; }}</style>
</head>
<body>
{body}
</body>
</html>"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
            f.write(HTML.format(body=body))
            html_path = f.name

        try:
            cwd = image_dir or os.path.dirname(output_path) or '.'
            ref_doc = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'reference.docx')
            pandoc_args = ['pandoc', html_path, '-o', output_path, '-f', 'html+tex_math_dollars']
            if os.path.isfile(ref_doc):
                pandoc_args.extend(['--reference-doc', ref_doc])
            result = subprocess.run(
                pandoc_args,
                cwd=cwd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                logger.error(f"Pandoc failed: {result.stderr}")
                raise HTTPException(status_code=500, detail=f"Word 导出失败: pandoc 转换错误")
        finally:
            if os.path.exists(html_path):
                os.remove(html_path)

        return output_path

    @staticmethod
    def _md_to_html(text: str, wrap_bare: bool = True) -> str:
        from html import escape as html_escape

        if not text:
            return ''

        html = text

        code_blocks = []
        def _save_cb(m):
            code_blocks.append(m.group(0))
            return f"__CB{len(code_blocks) - 1}__"
        html = re.sub(r'```[\s\S]*?```', _save_cb, html)

        inline_codes = []
        def _save_ic(m):
            inline_codes.append(m.group(1))
            return f"__IC{len(inline_codes) - 1}__"
        html = re.sub(r'`([^`]+)`', _save_ic, html)

        if wrap_bare:
            html = _wrap_bare_latex(html)

        html = _wrap_display_formulas(html)

        math_blocks = []
        def _save_mb(m):
            math_blocks.append(m.group(1).strip())
            return f"__MB{len(math_blocks) - 1}__"
        html = re.sub(r'\$\$([\s\S]*?)\$\$', _save_mb, html)

        math_inline = []
        def _save_mi(m):
            math_inline.append(m.group(1).strip())
            return f"__MI{len(math_inline) - 1}__"
        html = re.sub(r'\$([^$]+)\$', _save_mi, html)

        html = re.sub(r'^###### (.*)$', r'<h6>\1</h6>', html, flags=re.MULTILINE)
        html = re.sub(r'^##### (.*)$', r'<h5>\1</h5>', html, flags=re.MULTILINE)
        html = re.sub(r'^#### (.*)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.*)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.*)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.*)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

        html = re.sub(r'\*\*\*(.*?)\*\*\*', r'<b><i>\1</i></b>', html)
        html = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html)
        html = re.sub(r'\*(.*?)\*', r'<i>\1</i>', html)

        html = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1" style="max-width:100%">', html)
        html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', html)
        html = re.sub(r'^---$', r'<hr>', html, flags=re.MULTILINE)

        html = re.sub(r'^\s*[-*+●]\s+(.*)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        html = re.sub(r'(<li>.*?</li>\n?)+', lambda m: f'<ul>{m.group(0)}</ul>', html)

        for i, math in enumerate(math_blocks):
            html = html.replace(f"__MB{i}__", f"\\[{html_escape(math)}\\]")
        for i, math in enumerate(math_inline):
            html = html.replace(f"__MI{i}__", f"\\({html_escape(math)}\\)")

        for i, code in enumerate(inline_codes):
            html = html.replace(f"__IC{i}__", '<code>' + html_escape(code) + '</code>')
        for i, block in enumerate(code_blocks):
            content = re.sub(r'```\w*\n?', '', block, count=1)
            content = content.rstrip('`').rstrip()
            html = html.replace(f"__CB{i}__", '<pre><code>' + html_escape(content) + '</code></pre>')

        html_block_re = re.compile(r'^\s*</?(?:table|tr|t[dh]|thead|tbody|tfoot|caption|colgroup|col|div|h[1-6]|ul|ol|li|hr|pre|blockquote|p|img|br)[\s>]')
        closing_tag_re = re.compile(r'</[a-zA-Z][a-zA-Z0-9]*\s*>')
        lines = html.split('\n')
        result = []
        for line in lines:
            if not line.strip():
                result.append('')
            elif html_block_re.match(line) or re.match(r'^\s*</', line) or closing_tag_re.search(line):
                result.append(line)
            else:
                result.append(f'<p>{line}</p>')
        html = '\n'.join(result)
        html = re.sub(r'<p></p>', '', html)

        return html
