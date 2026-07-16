import os
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.database.schema import SCHEMA_SQL
from app.database.seed import seed_demo_data


@dataclass(frozen=True)
class DatabaseSettings:
    path: Path
    timeout_seconds: float = 5.0

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "DatabaseSettings":
        values = os.environ if environment is None else environment
        default_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "appointments-demo.sqlite3"
        )
        raw_path = values.get("APPOINTMENT_DB_PATH", str(default_path)).strip()
        if not raw_path:
            raise ValueError("APPOINTMENT_DB_PATH must not be blank.")
        raw_timeout = values.get("APPOINTMENT_DB_TIMEOUT_SECONDS", "5").strip()
        try:
            timeout = float(raw_timeout)
        except ValueError as error:
            raise ValueError(
                "APPOINTMENT_DB_TIMEOUT_SECONDS must be a number."
            ) from error
        if timeout < 1 or timeout > 30:
            raise ValueError(
                "APPOINTMENT_DB_TIMEOUT_SECONDS must be between 1 and 30."
            )
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        return cls(path=path, timeout_seconds=timeout)


class Database:
    """Small SQLite boundary for the demonstration appointment system."""

    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        self.settings = settings or DatabaseSettings.from_environment()

    def initialize(self) -> None:
        self.settings.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.execute("BEGIN")
            try:
                seed_demo_data(connection)
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.settings.path,
            timeout=self.settings.timeout_seconds,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
