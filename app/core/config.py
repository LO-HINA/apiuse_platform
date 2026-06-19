"""项目配置。

字段优先级:环境变量 > .env > 默认值。
"""
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "API Pool Test Platform"

    # ENV 决定环境差异化行为(日志格式、异常 traceback 暴露与否等)
    ENV: Literal["dev", "staging", "prod"] = "dev"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ------------------------------------------------------------------
    # JWT 鉴权
    # ------------------------------------------------------------------
    # JWT_SECRET 用 SecretStr 避免任何打印路径泄漏;空值会被启动校验拦下
    JWT_SECRET: SecretStr = SecretStr("")
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24

    # ------------------------------------------------------------------
    # 上游 AI(M2 之后由号池接管,这里仅 fake/单 channel 兜底)
    # ------------------------------------------------------------------
    AI_BASE_URL: str = ""
    AI_API_KEY: SecretStr = SecretStr("")
    AI_MODEL: str = "fake"
    USE_FAKE_AI: bool = False
    AI_SYSTEM_PROMPT: str = ""

    # ------------------------------------------------------------------
    # 运行参数
    # ------------------------------------------------------------------
    DEBUG: bool = True
    REQUEST_TIMEOUT: float = 30.0

    # 单会话保留的最大消息条数,内存版用它兜底,防止历史无限增长
    SESSION_MAX_MESSAGES: int = 100
    # M2 总量保护:单个会话内 trim 只能限制"一个桶"的大小,
    # 长时间运行时还需要限制活跃会话数量和闲置会话消息体。
    MAX_ACTIVE_SESSIONS: int = 1000
    SESSION_IDLE_TTL_MINUTES: int = 60

    # M2 channel failover:上游 5xx / 429 / timeout / 连接错误会短暂拉黑,
    # 让下一次调度优先尝试别的 key,避免一直打同一个坏上游。
    CHANNEL_BLACKLIST_SECONDS: int = 30

    # CORS:allow_origins=["*"] 不能和 allow_credentials=True 共存,默认列具体域名
    CORS_ALLOW_ORIGINS: list[str] = [
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ]

    # ------------------------------------------------------------------
    # 字段校验
    # ------------------------------------------------------------------

    @field_validator("CORS_ALLOW_ORIGINS")
    @classmethod
    def _check_cors_origins(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("CORS_ALLOW_ORIGINS 不能为空,至少要放一个具体域名")
        return v

    @field_validator("JWT_SECRET")
    @classmethod
    def _check_jwt_secret(cls, v: SecretStr) -> SecretStr:
        """启动期拦下"忘配 / 密钥过短"。"""
        raw = v.get_secret_value()
        if not raw:
            raise ValueError(
                "JWT_SECRET 必须在 .env 中显式配置,不能使用默认空值。"
                "可用 `python -c \"import secrets; print(secrets.token_urlsafe(48))\"` 生成。"
            )
        if len(raw) < 32:
            raise ValueError(
                f"JWT_SECRET 太短(当前 {len(raw)} 字符),HS256 推荐至少 32 字符。"
            )
        return v


settings = Settings()
