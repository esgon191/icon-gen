from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://icon:icon@postgres:5432/icon"

    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "icon-context"
    s3_region: str = "us-east-1"

    llm_provider: str = "stub"
    t2i_provider: str = "stub"

    context_sample_size: int = 10


settings = Settings()
