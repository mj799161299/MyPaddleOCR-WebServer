from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}  # SQLite需要此参数
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表并运行迁移"""
    Base.metadata.create_all(bind=engine)
    # 迁移: 添加 deleted_at 列 (如果不存在)
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(ocr_tasks)")).fetchall()]
        if 'deleted_at' not in cols:
            conn.execute(text("ALTER TABLE ocr_tasks ADD COLUMN deleted_at DATETIME"))
            conn.commit()
