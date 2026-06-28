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

    # ── LLM (DeepSeek) ──
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-v4-pro"
    LLM_FLASH_MODEL: str = "deepseek-v4-flash"  # 轻量任务（Rerank / 标题生成）

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

    # ── Rerank ──
    RERANK_BM25_SEGMENT_MAX_CHARS: int = 2000
    RERANK_BM25_TOP_K_PER_DOC: int = 3
    RERANK_CANDIDATE_MAX: int = 45

    # ── Pipeline ──
    PIPELINE_PLANNER_MAX_RETRIES: int = 3
    PIPELINE_SYNTHESIS_MAX_RETRIES: int = 3
    PIPELINE_RERANK_MAX_RETRIES: int = 2
    PIPELINE_RENDER_MAX_RETRIES: int = 1

    # ── SSE ──
    SSE_HEARTBEAT_INTERVAL: int = 15

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
