import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    应用配置，全部从环境变量读取。
    部署时在 .env 文件中设置即可。
    """

    # 访问密码，未设置则不启用认证
    ACCESS_PASSWORD: str = ""

    # 服务监听配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Cookie 签名密钥，未设置时自动生成（重启后 Cookie 失效）
    SECRET_KEY: str = os.urandom(32).hex()

    # 认证 Cookie 有效期（秒），默认 7 天
    AUTH_COOKIE_MAX_AGE: int = 7 * 24 * 3600

    # Telegram 通知配置
    TG_BOT_TOKEN: str = ""
    TG_CHAT_ID: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
