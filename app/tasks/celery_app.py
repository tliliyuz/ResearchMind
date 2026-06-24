import asyncio
from app.config import settings
from celery import Celery
import sys

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
)

# Windows: solo 池（默认），避免 eventlet/gevent 与 asyncio 冲突
if sys.platform == "win32":
    celery_app.conf.update(
        worker_pool="solo",
    )

# 注册任务模块（导入即注册 @celery_app.task 装饰的任务）
import app.tasks.research_task