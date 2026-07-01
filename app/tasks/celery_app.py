import asyncio
import logging
import sys

from celery import Celery
from celery.signals import worker_ready

from app.config import settings

logger = logging.getLogger(__name__)

# Windows 下 aiomysql 需要 SelectorEventLoop，Proactor 会卡死
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

celery_app = Celery(
    "researchmind",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # 队列路由：所有研究任务进入 research_task 队列
    task_default_queue="research_task",
    task_create_missing_queues=True,
    # 研究任务耗时较长，放宽超时
    task_soft_time_limit=600,
    task_time_limit=900,
    # Redis broker 消息可见性超时：Worker 崩溃后未 ACK 的消息多久后重新可见
    broker_transport_options={
        "visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT,
    },
    # Beat 定时调度：数据 TTL 清理
    beat_schedule={
        "cleanup_old_research_tasks": {
            "task": "app.tasks.periodic.cleanup_old_research_tasks",
            "schedule": 86400.0,  # 每天执行一次
            "kwargs": {
                "max_age_days": getattr(settings, "CLEANUP_TASK_MAX_AGE_DAYS", 30),
            },
        },
        "cleanup_stale_refresh_tokens": {
            "task": "app.tasks.periodic.cleanup_stale_refresh_tokens",
            "schedule": 86400.0,  # 每天执行一次
            "kwargs": {
                "max_age_days": getattr(settings, "CLEANUP_REFRESH_TOKEN_MAX_AGE_DAYS", 90),
            },
        },
    },
    beat_max_loop_interval=300,
)

# Windows: solo 池（默认），避免 eventlet/gevent 与 asyncio 冲突
if sys.platform == "win32":
    celery_app.conf.update(
        worker_pool="solo",
    )

# 注册任务模块（导入即注册 @celery_app.task 装饰的任务）
import app.tasks.research_task
import app.tasks.periodic  # noqa: F401


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """Worker 启动完成时触发恢复检查。

    扫描 running 任务，若任务级锁已消失（说明旧 Worker 崩溃），
    则重新投递任务，实现不依赖 Redis visibility_timeout 的快速恢复。
    """
    logger.info("Celery Worker 已就绪，触发过时任务恢复检查")
    try:
        from app.tasks.recovery import recover_stale_tasks

        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        recovered = loop.run_until_complete(recover_stale_tasks(check_lock=True))
        if recovered:
            logger.warning("Worker 就绪恢复：已重新投递 %d 个任务: %s", len(recovered), recovered)
    except Exception:
        logger.exception("Worker 就绪恢复检查失败")
