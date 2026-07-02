#!/bin/sh
# ResearchMind 后端统一入口脚本
# 支持角色：web / worker / beat / migrate

set -e

ROLE="${1:-web}"

# 注意：不再自动清空 PROMETHEUS_MULTIPROC_DIR。
# web / worker / beat 三个容器共享同一个 prometheus_multiproc 卷，
# 任意一方清空都会导致其他容器已写入的指标文件丢失。
# 如需彻底清理旧指标，可手动执行：docker compose down -v

case "$ROLE" in
    web)
        echo "[entrypoint] 启动 FastAPI Web (uvicorn workers=${UVICORN_WORKERS:-1})"
        exec uvicorn app.main:app \
            --host 0.0.0.0 \
            --port 8000 \
            --workers "${UVICORN_WORKERS:-1}" \
            --proxy-headers \
            --forwarded-allow-ips='*'
        ;;
    worker)
        echo "[entrypoint] 启动 Celery Worker (pool=${CELERY_WORKER_POOL:-solo})"
        exec celery -A app.tasks.celery_app worker \
            --loglevel="${CELERY_LOG_LEVEL:-info}" \
            --pool="${CELERY_WORKER_POOL:-solo}" \
            --concurrency="${CELERY_WORKER_CONCURRENCY:-1}" \
            --hostname="worker@%h"
        ;;
    beat)
        echo "[entrypoint] 启动 Celery Beat"
        exec celery -A app.tasks.celery_app beat \
            --loglevel="${CELERY_LOG_LEVEL:-info}" \
            --schedule="/var/lib/celery/beat-schedule" \
            --scheduler=celery.beat.PersistentScheduler
        ;;
    migrate)
        echo "[entrypoint] 执行 Alembic 迁移"
        exec alembic upgrade head
        ;;
    *)
        echo "[entrypoint] 未知角色: $ROLE"
        echo "用法: docker-entrypoint.sh [web|worker|beat|migrate]"
        exit 1
        ;;
esac
