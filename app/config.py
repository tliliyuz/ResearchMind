"""
ResearchMind 全局配置单例。

基于 pydantic-settings，所有环境变量从 .env 文件加载。
配置项按功能域分组：应用 / MySQL / Redis / LLM / 搜索 / JWT / CORS。

禁止在各模块中硬编码配置值 —— 统一通过 `settings` 单例读取。
"""

from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置单例，从 .env 加载所有环境变量。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 应用 ──
    APP_NAME: str = "ResearchMind"
    DEBUG: bool = True
    ENV: str = "development"

    # ── MySQL ──
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "researchmind"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "researchmind"

    # ── Redis / Celery ──
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_IDEMPOTENCY_LOCK_TTL: int = 600  # Step 幂等锁 TTL（秒），防重复入队

    # ── Worker 崩溃恢复 ──
    # 任务级锁 TTL（租约模式）：正常执行时定期刷新，崩溃后旧锁在 TTL 内过期
    # 配置目标：Worker 崩溃后约 30s 内被超时监察者标记为 failed
    CELERY_TASK_LOCK_TTL: int = 20
    # 任务级锁刷新间隔（秒），必须显著小于 TTL，确保正常执行时锁始终存在
    CELERY_LOCK_REFRESH_INTERVAL: int = 10
    # Worker 超时监察者：锁缺失持续该时长后标记任务 failed
    WORKER_TIMEOUT_SECONDS: int = 10
    # pending 任务超时：任务创建/重试后该时长内未被 Worker 拾取则标记 failed
    PENDING_TASK_TIMEOUT_SECONDS: int = 30
    # 监察者扫描间隔（秒）
    WORKER_TIMEOUT_CHECK_INTERVAL: int = 5
    # 启动宽限期：started_at 在该时间内即使锁缺失也不标记失败（避免启动瞬间 race）
    WORKER_TIMEOUT_GRACE_SECONDS: int = 5
    # 启动恢复阈值：running 任务超过该时间无活跃 Worker 心跳/锁，则重新投递
    STALE_TASK_RECOVERY_SECONDS: int = 60
    STARTUP_RECOVERY_ENABLED: bool = True    # 启动时自动恢复过时 running 任务
    # Redis broker visibility_timeout：明确配置，避免依赖 Celery 默认 1h
    CELERY_VISIBILITY_TIMEOUT: int = 1800

    # ── LLM (DeepSeek) ──
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-v4-pro"
    LLM_FLASH_MODEL: str = "mimo-v2.5"  # 轻量任务（Rerank / 标题生成）

    # [v2] 分级模型（预留）
    # LLM_PLANNING_MODEL: str = "deepseek-v4-pro"
    # LLM_BIG_MODEL: str = "deepseek-v4-pro"

    # ── 搜索 ──
    TAVILY_API_KEY: str = ""
    TAVILY_BASE_URL: str = "https://api.tavily.com"
    TAVILY_MAX_RESULTS_PER_QUERY: int = 5
    TAVILY_SEARCH_DEPTH: str = "advanced"
    TAVILY_TOTAL_RESULTS_LIMIT: int = 25

    # ── Fetch ──
    FETCH_TIMEOUT: int = 15
    FETCH_MAX_CONTENT_LENGTH: int = 102400  # 100KB
    FETCH_MAX_BODY_SIZE: int = 2 * 1024 * 1024  # 2MB，HTTP 响应体硬上限
    FETCH_MAX_URLS_PER_TASK: int = 15  # 每任务 Fetch URL 硬上限
    FETCH_MAX_RETRIES: int = 1

    # ── Token 估算 ──
    TOKEN_CHINESE_RATIO: float = 1.5
    TOKEN_ENGLISH_RATIO: float = 4.0
    TOKEN_CHINESE_THRESHOLD: float = 0.3
    TOKEN_BUDGET_SOFT_LIMIT: int = 8000  # Rerank/Synthesis/Render Prompt 软上限

    # ── Rerank ──
    RERANK_BM25_SEGMENT_MAX_CHARS: int = 2000
    RERANK_BM25_TOP_K_PER_DOC: int = 3
    RERANK_CANDIDATE_MAX: int = 45

    # ── Pipeline ──
    PIPELINE_PLANNER_MAX_RETRIES: int = 3
    PIPELINE_SYNTHESIS_MAX_RETRIES: int = 3
    PIPELINE_RERANK_MAX_RETRIES: int = 2
    PIPELINE_RENDER_MAX_RETRIES: int = 1

    # ── Agent Runtime ──
    MAX_AGENT_ITERATIONS: int = 30
    AGENT_WORKING_MEMORY_MAX_ENTRIES: int = 20

    # ── SSE ──
    SSE_HEARTBEAT_INTERVAL: int = 15

    # ── 可观测性 / Prometheus ──
    METRICS_ENABLED: bool = True
    METRICS_ENDPOINT: str = "/metrics"
    METRICS_QUEUE_REFRESH_INTERVAL: int = 15
    METRICS_WORKER_REFRESH_INTERVAL: int = 15
    METRICS_WORKER_PING_TIMEOUT: float = 5.0

    # ── 限流（Phase 4 激活，代码提前就位）──
    RATE_LIMIT_ENABLED: bool = False  # Phase 4 压测后启用
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_RESEARCH_PER_MINUTE: int = 5    # 创建研究任务 5次/分钟
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10      # 登录/注册 10次/分钟
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 120   # 全局默认 120次/分钟

    # ── JWT ──
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_TOKEN_SECRET_KEY: str = ""

    # ── CORS ──
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的 CORS_ORIGINS 解析为列表。"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        """
        动态拼接 MySQL 异步连接串（FastAPI 运行时 + Alembic 迁移共用）。

        - 通过 quote_plus 安全处理密码中的特殊字符
        - charset=utf8mb4 支持完整 Unicode 字符集
        - time_zone='+00:00' 由 core/database.py 的 connect 钩子统一设置，
          确保四层 UTC 统一（此处不再重复通过 init_command 设置）
        """
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{quote_plus(self.MYSQL_PASSWORD)}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )


# 全局配置单例 —— 所有模块通过 `from app.config import settings` 引用
settings = Settings()
