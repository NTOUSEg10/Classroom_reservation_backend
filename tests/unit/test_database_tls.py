import ssl
from unittest.mock import AsyncMock

import pytest

from app.config import Settings, database_ssl_context
from app.main import create_app


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_local_development_database_keeps_non_tls_fixture(host):
    settings = Settings(
        environment="test",
        database_url=f"postgresql://test:fixture@{host}:5432/ntou",
        _env_file=None,
    )
    assert database_ssl_context(settings) is None


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_remote_database_requires_certificate_and_hostname_verification(
    environment,
):
    settings = Settings(
        environment="test",
        database_url="postgresql://test:fixture@pooler.example.test:5432/ntou?sslmode=disable",
        _env_file=None,
    ).model_copy(update={"environment": environment})
    context = database_ssl_context(settings)
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_production_loopback_database_still_requires_tls():
    settings = Settings(
        environment="test",
        database_url="postgresql://test:fixture@127.0.0.1:5432/ntou",
        _env_file=None,
    ).model_copy(update={"environment": "production"})
    context = database_ssl_context(settings)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_custom_database_ca_is_loaded_with_full_verification(monkeypatch):
    original_context = ssl.create_default_context
    captured = []

    def load_context(*, cafile):
        captured.append(cafile)
        return original_context()

    monkeypatch.setattr("app.config.ssl.create_default_context", load_context)
    settings = Settings(
        environment="test",
        database_url="postgresql://test:fixture@pooler.example.test:5432/ntou",
        database_ssl_ca_file="fixture-ca.pem",
        _env_file=None,
    )
    context = database_ssl_context(settings)
    assert captured == ["fixture-ca.pem"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_invalid_ca_fails_closed_without_echoing_paths(
    tmp_path, exists
):
    path = tmp_path / "private-fixture-ca.pem"
    if exists:
        path.write_text("invalid-private-certificate-fixture", encoding="utf-8")
    settings = Settings(
        environment="test",
        database_url="postgresql://test:private-password-fixture@pooler.example.test:5432/ntou",
        database_ssl_ca_file=str(path),
        _env_file=None,
    )
    with pytest.raises(RuntimeError, match="DATABASE_SSL_CA_FILE") as error:
        database_ssl_context(settings)
    assert "private-" not in str(error.value)
    assert error.value.__suppress_context__ is True


async def test_application_pool_receives_verified_tls_even_during_development(
    monkeypatch,
):
    pool = AsyncMock()
    create_pool = AsyncMock(return_value=pool)
    monkeypatch.setattr("app.main.asyncpg.create_pool", create_pool)
    settings = Settings(
        environment="development",
        database_url="postgresql://test:fixture@pooler.example.test:5432/ntou?sslmode=disable",
        _env_file=None,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        context = create_pool.call_args.kwargs["ssl"]
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True
    pool.close.assert_awaited_once()
