"""Create a mode-0600 libpq service file from a mounted PostgreSQL DSN secret.

The DSN is read from a *_FILE environment variable; it is never accepted as a
command-line argument, echoed, or written to logs. Only sslmode=verify-full is
accepted so backup and restore helpers retain certificate and hostname checks.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def _libpq_value(value: str) -> str:
    if any(char in value for char in ("\r", "\n", "\x00")):
        raise ValueError("connection_value_contains_control_character")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def service_text(database_url: str, service_name: str) -> str:
    parsed = urlsplit(database_url.strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    modes = query.get("sslmode", [])
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.hostname
        or not parsed.path.strip("/")
        or len(modes) != 1
        or modes[0].strip().lower() != "verify-full"
    ):
        raise ValueError("database_url_must_be_postgresql_with_sslmode_verify_full")
    if not service_name or any(char in service_name for char in "[]\r\n"):
        raise ValueError("invalid_service_name")

    fields = {
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "dbname": unquote(parsed.path.lstrip("/")),
        "sslmode": "verify-full",
    }
    if parsed.username is not None:
        fields["user"] = unquote(parsed.username)
    if parsed.password is not None:
        fields["password"] = unquote(parsed.password)
    root_certs = query.get("sslrootcert", [])
    if len(root_certs) > 1:
        raise ValueError("database_url_has_duplicate_sslrootcert")
    if root_certs and root_certs[0]:
        fields["sslrootcert"] = root_certs[0]

    body = [f"[{service_name}]"]
    body.extend(f"{key}={_libpq_value(value)}" for key, value in fields.items())
    return "\n".join(body) + "\n"


def write_service_file(
    *,
    output_path: str | Path,
    environment_name: str,
    service_name: str,
    environ: dict[str, str] | None = None,
) -> Path:
    source = os.environ if environ is None else environ
    secret_path = source.get(environment_name, "").strip()
    if not secret_path:
        raise RuntimeError(f"{environment_name}_is_required")
    try:
        database_url = Path(secret_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"{environment_name}_could_not_be_read") from exc
    if not database_url:
        raise RuntimeError(f"{environment_name}_is_empty")

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(service_text(database_url, service_name), encoding="utf-8")
    os.chmod(target, 0o600)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--environment-name", required=True)
    parser.add_argument("--service-name", required=True)
    args = parser.parse_args()
    write_service_file(
        output_path=args.output,
        environment_name=args.environment_name,
        service_name=args.service_name,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
