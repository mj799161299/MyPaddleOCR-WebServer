FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制后端代码
COPY backend/ .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 创建必要目录
RUN mkdir -p uploads exports

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "main.py"]
