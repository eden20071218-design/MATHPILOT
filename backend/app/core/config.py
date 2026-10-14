from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MathPilot API"
    database_url: str = "postgresql+psycopg://mathpilot:mathpilot@localhost:5432/mathpilot"
    api_prefix: str = "/api/v1"
    redis_url: str = "redis://localhost:6379/0"
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"
    reminder_api_secret: str = ""
    admin_api_key: str = ""
    cookie_secure: bool = False
    frontend_origin: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000/api/v1"
    deepseek_enabled: bool = False
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    push_allowed_hosts: str = "fcm.googleapis.com,updates.push.services.mozilla.com,web.push.apple.com,notify.windows.com"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

