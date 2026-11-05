import pytest

from app.config import Settings, validate_database_configuration


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
