from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.ops.pg_service import service_text, write_service_file


def test_service_text_requires_verified_tls_and_escapes_credentials():
    value = service_text(
        "postgresql://db-user:p%40ss%5Cword@db.example:5432/ugai"
        "?sslmode=verify-full&sslrootcert=%2Frun%2Fsecrets%2Fca.pem",
        "ugai_backup",
    )
    assert "[ugai_backup]" in value
    assert 'user="db-user"' in value
    assert 'password="p@ss\\\\word"' in value
    assert 'sslmode="verify-full"' in value
    assert 'sslrootcert="/run/secrets/ca.pem"' in value


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user:pass@db.example/app",
        "postgresql://user:pass@db.example/app?sslmode=require",
        "postgresql://user:pass@db.example/app?sslmode=verify-ca",
        "postgresql://user:pass@db.example/app?sslmode=require&sslmode=verify-full",
        "mysql://user:pass@db.example/app?sslmode=verify-full",
    ],
)
def test_service_text_rejects_unverified_or_ambiguous_dsn(dsn):
    with pytest.raises(ValueError):
        service_text(dsn, "ugai_backup")


def test_service_file_reads_mounted_dsn_and_is_private(tmp_path):
    dsn_file = tmp_path / "db-url"
    dsn_file.write_text(
        "postgresql://user:pass@db.example/ugai?sslmode=verify-full\n",
        encoding="utf-8",
    )
    output = tmp_path / "private" / "pg_service.conf"
    written = write_service_file(
        output_path=output,
        environment_name="DATABASE_URL_FILE",
        service_name="ugai_backup",
        environ={"DATABASE_URL_FILE": str(dsn_file)},
    )
    assert written == output
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "pass" in output.read_text(encoding="utf-8")
    assert str(dsn_file) not in output.read_text(encoding="utf-8")


def test_backup_and_restore_shell_scripts_parse():
    root = Path(__file__).resolve().parents[1]
    for script in (
        root / "scripts/ops/backup_postgres_encrypted.sh",
        root / "scripts/ops/restore_postgres_isolated.sh",
    ):
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
