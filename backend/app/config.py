from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg2://foodrescue:foodrescue@localhost:5433/foodrescue"
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "foodrescue"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    jwt_secret: str = "dev-secret-change-me-please-32-bytes-min"
    jwt_expire_minutes: int = 720
    inbox_dir: str = "data/inbox"
    api_internal_url: str = "http://127.0.0.1:8000"
    sim_direct_ingest: bool = True
    match_radius_km: float = 15.0
    cors_origins: str = "http://localhost:5173,http://localhost:5174"


settings = Settings()
