# ResearchMind 后端统一镜像
# 支持多角色：web / worker / beat / migrate
#
# 构建：
#   docker build -f Dockerfile.backend -t researchmind/backend .
# 运行：
#   docker run --rm researchmind/backend web
#   docker run --rm researchmind/backend worker
#   docker run --rm researchmind/backend beat
#   docker run --rm researchmind/backend migrate

FROM python:3.12-slim AS builder

WORKDIR /app

# 替换 Debian 源为阿里云镜像，避免国内服务器 apt-get 卡住
RUN sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://security.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 先单独复制 requirements，利用 Docker 缓存层
COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
    && pip install --no-cache-dir --user -r requirements.txt

# ── 运行镜像 ──
FROM python:3.12-slim AS runtime

WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/root/.local/bin:$PATH \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus

# 仅安装运行时所需的最小系统依赖（同样使用阿里云源）
RUN sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://security.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libffi8 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /tmp/prometheus /var/lib/celery

# 从 builder 复制已安装的 Python 包
COPY --from=builder /root/.local /root/.local

# 复制应用代码
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# 确保 entrypoint 可执行
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["web"]
