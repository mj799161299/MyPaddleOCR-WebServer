import os
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from config import settings
from database import init_db, SessionLocal
from middleware import SecurityHeadersMiddleware, RateLimitMiddleware
from routers import auth, upload, ocr, export, admin, invitation_codes
from models.user import User
from models.invitation_code import InvitationCode
from utils.security import get_password_hash

app = FastAPI(
    title=settings.APP_NAME,
    description="OCR扫描工具 Web API - 支持图片上传、OCR识别、结果导出",
    version="1.0.0"
)

# ---- 中间件栈（按添加顺序执行） ----

# 1. 安全响应头
app.add_middleware(SecurityHeadersMiddleware)

# 2. 速率限制
app.add_middleware(RateLimitMiddleware)

# 3. 受信主机校验
if settings.TRUSTED_HOSTS != ["*"]:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.TRUSTED_HOSTS,
    )

# 4. CORS 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.EXPORT_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(ocr.router)
app.include_router(export.router)
app.include_router(admin.router)
app.include_router(invitation_codes.router)


# ---- 生命周期事件 ----

@app.on_event("startup")
async def startup():
    init_db()
    _migrate_db()
    _create_default_admin()
    _recover_stuck_tasks()

    protocol = "https" if settings.SSL_ENABLED else "http"
    print(f"{settings.APP_NAME} started on {protocol}://{settings.HOST}:{settings.PORT}")
    print(f"Upload dir:  {settings.UPLOAD_DIR}")
    print(f"Export dir:  {settings.EXPORT_DIR}")
    print(f"OCR server:  {settings.OCR_SERVER_URL}")
    print(f"Rate limit:  {'enabled' if settings.RATE_LIMIT_ENABLED else 'disabled'}")
    print(f"CORS origins: {settings.CORS_ORIGINS}")
    print(f"Trusted hosts: {settings.TRUSTED_HOSTS}")

    # 预初始化 OCR 管道（避免在线程中首次初始化失败）
    _preinit_ocr_pipeline()


@app.on_event("shutdown")
async def shutdown():
    """关闭线程池，等待正在执行的任务完成。"""
    from routers.ocr import _ocr_executor
    _ocr_executor.shutdown(wait=True, cancel_futures=False)
    print("[OK] OCR executor shut down")


# ---- 内部辅助函数 ----

def _preinit_ocr_pipeline():
    """在应用启动时预先初始化 PaddleOCRVL 管道。

    管道创建涉及 GPU 初始化和模型加载，在 uvicorn 子进程中
    直接初始化比在线程池中首次调用更稳定。
    """
    try:
        from services.ocr_service import OCRService
        svc = OCRService(settings.OCR_SERVER_URL)
        pipe = svc._get_pipeline()
        print(f"[OK] PaddleOCRVL pipeline pre-initialized: {type(pipe).__name__}")
    except Exception as e:
        import traceback
        print(f"[WARN] PaddleOCRVL pre-init failed: {e}")
        print(traceback.format_exc())
        print("[INFO] Pipeline will be created lazily on first OCR request")


def _migrate_db():
    db = SessionLocal()
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.bind)
        if "users" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("users")]
            if "role" not in cols:
                db.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(10) DEFAULT 'user'"))
            if "is_active" not in cols:
                db.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
            if "invited_by" not in cols:
                db.execute(text("ALTER TABLE users ADD COLUMN invited_by INTEGER"))
            if "invitation_code_id" not in cols:
                db.execute(text("ALTER TABLE users ADD COLUMN invitation_code_id INTEGER"))
            db.commit()

        if "invitation_codes" not in inspector.get_table_names():
            InvitationCode.__table__.create(db.bind)
    except Exception as e:
        print(f"[WARN] DB migration error: {e}")
        db.rollback()
    finally:
        db.close()


def _recover_stuck_tasks():
    """将崩溃后残留的 processing 状态任务标记为 failed。"""
    from models.task import OCRTask, TaskStatus
    db = SessionLocal()
    try:
        stuck = db.query(OCRTask).filter(OCRTask.status == TaskStatus.PROCESSING).all()
        if stuck:
            for t in stuck:
                t.status = TaskStatus.FAILED
            db.commit()
            print(f"[OK] Recovered {len(stuck)} stuck task(s)")
    except Exception as e:
        print(f"[WARN] Stuck task recovery error: {e}")
        db.rollback()
    finally:
        db.close()


def _create_default_admin():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == "mjsk").first()
        if not existing:
            admin = User(
                username="mjsk",
                hashed_password=get_password_hash("mjsk"),
                role="admin",
                is_active=True
            )
            db.add(admin)
            db.commit()
            print("[OK] Default admin user created (mjsk)")
        else:
            existing.role = "admin"
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ---- 通用路由 ----

@app.get("/", summary="首页")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running"
    }


@app.get("/health", summary="健康检查")
async def health_check():
    return {"status": "ok"}


# ---- 启动入口 ----

if __name__ == "__main__":
    import uvicorn

    kwargs = {}
    if settings.SSL_ENABLED:
        kwargs["ssl_certfile"] = settings.SSL_CERTFILE
        kwargs["ssl_keyfile"] = settings.SSL_KEYFILE
        if settings.SSL_KEYFILE_PASSWORD:
            kwargs["ssl_keyfile_password"] = settings.SSL_KEYFILE_PASSWORD

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        **kwargs,
    )
