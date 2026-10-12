import ssl
from urllib.parse import parse_qs, urlparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    environment: str = "development"
    database_url: str = Field(default="", repr=False)
    database_ssl_ca_file: str = Field(default="", repr=False)
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_service_key: str = Field(
        default="",
        repr=False,
        validation_alias=AliasChoices(
            "SUPABASE_SECRET_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "supabase_service_key",
        ),
    )
    frontend_origin: str = "http://localhost:5173"
    vapid_public_key: str = ""
    dispatch_secret: str = Field(default="", repr=False)
    demo_data: bool = True
    pool_min_size: int = Field(default=2, ge=1, le=100)
    pool_max_size: int = Field(default=20, ge=1, le=100)
    auth_rate_limit: int = Field(default=10, ge=1)
    auth_ip_rate_limit: int = Field(default=300, ge=1)
    auth_rate_window: int = Field(default=60, ge=1)
    enable_notification_worker: bool = True
    push_dispatch_enabled: bool = False

    @model_validator(mode="after")
    def secure_production(self):
        if self.supabase_publishable_key.startswith("sb_secret_"):
            raise ValueError(
                "A secret API key cannot be used as the public key"
            )
        if self.pool_min_size > self.pool_max_size:
            raise ValueError("pool_min_size cannot exceed pool_max_size")
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("Unknown environment")
        if self.supabase_url:
            parsed = urlparse(self.supabase_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Invalid Supabase URL")
            if parsed.scheme == "http" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("Remote Supabase requires HTTPS")
        if self.environment == "production":
            if (
                urlparse(self.supabase_url).scheme != "https"
                or urlparse(self.frontend_origin).scheme != "https"
            ):
                raise ValueError(
                    "Production requires HTTPS Supabase and frontend URLs"
                )
            if not all(
                (
                    self.database_url,
                    self.supabase_publishable_key,
                    self.supabase_service_key,
                    self.dispatch_secret,
                    self.vapid_public_key,
                )
            ):
                raise ValueError(
                    "Production service configuration is incomplete"
                )
            if self.demo_data:
                raise ValueError("Production cannot use demonstration data")
            if urlparse(self.database_url).username in {
                "postgres",
                "supabase_admin",
            }:
                raise ValueError(
                    "Production must use a restricted application DB login"
                )
            db_query = parse_qs(urlparse(self.database_url).query)
            if db_query.get("sslmode", ["verify-full"])[0] not in {
                "verify-ca",
                "verify-full",
            }:
                raise ValueError(
                    "Production DB TLS must verify the certificate"
                )
        return self


def database_ssl_context(settings: Settings) -> ssl.SSLContext | None:
    try:
        host = urlparse(settings.database_url).hostname
    except ValueError:
        raise ValueError("Invalid DATABASE_URL") from None
    if settings.environment != "production" and host in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        return None
    try:
        # An explicit context overrides weaker sslmode options in the DSN.
        return ssl.create_default_context(
            cafile=settings.database_ssl_ca_file or None
        )
    except (OSError, ValueError):
        raise RuntimeError(
            "Database CA certificate could not be loaded; check DATABASE_SSL_CA_FILE"
        ) from None
