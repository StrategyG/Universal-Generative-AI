import pytest

from app.config import (
    Settings,
    apply_secret_file_environment,
    validate_database_configuration,
    validate_rate_limit_configuration,
)


def test_development_database_configuration_remains_flexible():
    validate_database_configuration(Settings(environment="development", database_url=""))
    validate_database_configuration(
        Settings(environment="test", database_url="postgresql://localhost/test")
    )


@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "postgresql://user:pass@db.example:5432/app",
        "postgresql://user:pass@db.example:5432/app?sslmode=prefer",
        "postgresql://user:pass@db.example:5432/app?sslmode=require",
        "postgresql://user:pass@db.example:5432/app?sslmode=verify-ca",
        (
            "postgresql://user:pass@db.example:5432/app"
            "?sslmode=require&sslmode=verify-full"
        ),
        "mysql://user:pass@db.example:3306/app?sslmode=verify-full",
    ],
)
def test_production_rejects_unverified_or_ambiguous_database_urls(database_url):
    with pytest.raises(RuntimeError):
        validate_database_configuration(
            Settings(environment="production", database_url=database_url)
        )


def test_production_accepts_verify_full():
    validate_database_configuration(
        Settings(
            environment="production",
            database_url=(
                "postgresql://user:pass@db.example:5432/app"
                "?sslmode=verify-full"
            ),
        )
    )
    validate_database_configuration(
        Settings(
            environment="prod",
            database_url=(
                "postgres://user:pass@db.example:5432/app"
                "?sslmode=verify-full&sslrootcert=%2Fetc%2Fssl%2Fca.pem"
            ),
        )
    )



def test_secret_file_loader_reads_value_and_strips_only_trailing_newlines(tmp_path):
    secret_file = tmp_path / "database-url"
    secret_file.write_text("postgresql://user:pa\\ss@db.example/app\n", encoding="utf-8")
    environ = {"DATABASE_URL_FILE": str(secret_file)}
    apply_secret_file_environment(environ)
    assert environ["DATABASE_URL"] == "postgresql://user:pa\\ss@db.example/app"


def test_secret_file_loader_rejects_ambiguous_sources(tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text("mounted-secret\\n", encoding="utf-8")
    environ = {
        "WORKER_ADMIN_TOKEN": "inline-secret",
        "WORKER_ADMIN_TOKEN_FILE": str(secret_file),
    }
    with pytest.raises(RuntimeError, match="cannot both be configured"):
        apply_secret_file_environment(environ)


@pytest.mark.parametrize(
    "settings",
    [
        Settings(environment="production", rate_limit_enabled=False),
        Settings(environment="production", rate_limit_enabled=True, rate_limit_backend="memory"),
        Settings(
            environment="production",
            rate_limit_enabled=True,
            rate_limit_backend="redis",
            rate_limit_redis_url="redis://redis:6379/0",
            metrics_token="metrics-secret",
        ),
    ],
)
def test_production_rate_limit_configuration_fails_closed(settings):
    with pytest.raises(RuntimeError):
        validate_rate_limit_configuration(settings)


def test_production_rate_limit_configuration_requires_tls_and_metrics_token():
    validate_rate_limit_configuration(
        Settings(
            environment="production",
            rate_limit_enabled=True,
            rate_limit_backend="redis",
            rate_limit_redis_url="rediss://ugai:redis-secret@redis.example:6380/0",
            metrics_token="long-random-token",
        )
    )
    with pytest.raises(RuntimeError, match="METRICS_TOKEN"):
        validate_rate_limit_configuration(
            Settings(
                environment="production",
                rate_limit_enabled=True,
                rate_limit_backend="redis",
                rate_limit_redis_url="rediss://ugai:redis-secret@redis.example:6380/0",
            )
        )



def test_production_rate_limit_requires_redis_acl_password():
    with pytest.raises(RuntimeError, match="ACL password"):
        validate_rate_limit_configuration(
            Settings(
                environment="production",
                rate_limit_enabled=True,
                rate_limit_backend="redis",
                rate_limit_redis_url="rediss://redis.example:6380/0",
                metrics_token="long-random-token",
            )
        )
