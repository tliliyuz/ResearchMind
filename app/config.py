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

    # ── LLM (DeepSeek) ──
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-v4-pro"

    # [v2] 分级模型（预留）
    # LLM_PLANNING_MODEL: str = "deepseek-v4-pro"
    # LLM_FLASH_MODEL: str = "deepseek-v4-flash"

    # ── 搜索 ──
    TAVILY_API_KEY: str = ""

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
        动态拼接 MySQL 异步连接串。

        - 通过 quote_plus 安全处理密码中的特殊字符
        - 连接时强制设置 time_zone='+00:00' 确保四层 UTC 统一
        - charset=utf8mb4 支持完整 Unicode 字符集
        """
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{quote_plus(self.MYSQL_PASSWORD)}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4&init_command=SET time_zone='%2B00:00'"
        )


# 全局配置单例 —— 所有模块通过 `from app.config import settings` 引用
settings = Settings()
