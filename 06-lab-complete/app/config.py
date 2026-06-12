"""
Configuration management using pydantic-settings.
All config is loaded from environment variables for 12-Factor App compliance.

Cách hoạt động:
  1. Đọc từ environment variables (ưu tiên cao nhất)
  2. Đọc từ file .env (nếu có)
  3. Dùng giá trị mặc định (nếu không tìm thấy)

Ví dụ override:
  export PORT=9000
  export REDIS_URL=redis://my-redis:6379/1
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Server ──────────────────────────────────────────────
    PORT: int = Field(
        default=8000,
        description="Port để chạy server. Railway/Render inject tự động.",
    )
    HOST: str = Field(
        default="0.0.0.0",
        description="Bind address. 0.0.0.0 để nhận kết nối từ bên ngoài container.",
    )
    ENVIRONMENT: str = Field(
        default="production",
        description="Môi trường: development, staging, production.",
    )
    DEBUG: bool = Field(
        default=False,
        description="Bật debug mode. KHÔNG bật trong production.",
    )

    # ── App Info ────────────────────────────────────────────
    APP_NAME: str = Field(
        default="Production AI Agent",
        description="Tên ứng dụng, hiển thị trong /health.",
    )
    APP_VERSION: str = Field(
        default="1.0.0",
        description="Phiên bản app.",
    )

    # ── Security ────────────────────────────────────────────
    AGENT_API_KEY: str = Field(
        default="change-me-in-production",
        description="API key để authenticate requests. BẮT BUỘC thay đổi trong production.",
    )
    JWT_SECRET: str = Field(
        default="change-me-jwt-secret",
        description="Secret key để sign JWT tokens.",
    )

    # ── Redis ───────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection URL. Mặc định trỏ đến service 'redis' trong Docker Compose.",
    )

    # ── Rate Limiting ───────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = Field(
        default=10,
        description="Số request tối đa mỗi user mỗi phút.",
    )

    # ── Cost Guard ──────────────────────────────────────────
    MONTHLY_BUDGET_USD: float = Field(
        default=10.0,
        description="Budget tối đa (USD) mỗi user mỗi tháng.",
    )

    # ── Logging ─────────────────────────────────────────────
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


settings = Settings()
