import os
import secrets
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "OCR扫描工具 Web版"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # JWT配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24小时
    AUTO_GENERATE_SECRET_KEY: bool = True

    # 数据库配置
    DATABASE_URL: str = "sqlite:///./ocr_web.db"

    # 文件存储配置
    UPLOAD_DIR: str = os.path.join(os.path.dirname(__file__), "uploads")
    EXPORT_DIR: str = os.path.join(os.path.dirname(__file__), "exports")
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    MAX_REQUEST_SIZE: int = 50 * 1024 * 1024  # 50MB

    # CORS配置
    CORS_ORIGINS: list = ["http://localhost:5173", "http://localhost:3000"]
    CORS_ALLOW_CREDENTIALS: bool = True

    # SSL / HTTPS 配置
    SSL_ENABLED: bool = False
    SSL_CERTFILE: str = ""
    SSL_KEYFILE: str = ""
    SSL_KEYFILE_PASSWORD: str = ""

    # 速率限制
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "120/minute"
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_UPLOAD: str = "30/minute"
    RATE_LIMIT_REGISTER: str = "5/minute"

    # 受信主机（Host 头校验）
    TRUSTED_HOSTS: list = ["*"]

    # OCSP / Cert 自动续期（预留）
    SSL_AUTO_RENEW: bool = False

    # OCR服务配置
    OCR_SERVER_URL: str = "http://127.0.0.1:7950/v1"

    class Config:
        env_file = ".env"


settings = Settings()

# 启动时自动生成 SECRET_KEY（仅当使用默认值或配置了自动生成）
if settings.AUTO_GENERATE_SECRET_KEY and settings.SECRET_KEY == "your-secret-key-change-in-production":
    settings.SECRET_KEY = secrets.token_urlsafe(64)
