"""Generation-scoped SQLite ledger, compatible with the retired Ops service."""
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Mapping, Optional

from .policy import COOLDOWN_SECONDS

_DATABASE_VERSION = 2


class StateError(RuntimeError):
    pass


@dataclass(frozen=True)
class FundingRequest:
    address: str
    address_key: str
    request_id: str
    requester_ip: str


@dataclass(frozen=True)
class Reservation:
    kind: str
    status: Optional[str] = None
    result: Optional[dict] = None
    http_status: Optional[int] = None
    error_code: Optional[str] = None
    error_reason: Optional[str] = None
    retry_after_seconds: Optional[int] = None


class FundingState:
    """SQLite idempotency and actual-funding cooldown for one Anvil generation."""

    def __init__(self, path: Path, now=time.time) -> None:
        self.path = path
        self.now = now
        self._connection: Optional[sqlite3.Connection] = None
        self._open()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise StateError("faucet database is closed")
        return self._connection

    def _open(self) -> None:
        try:
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) STRICT;
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    address_key TEXT NOT NULL,
                    requester_ip TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('reserved', 'uncertain', 'failed', 'completed')),
                    http_status INTEGER,
                    error_code TEXT,
                    error_reason TEXT,
                    result_json TEXT,
                    funded_at REAL
                ) STRICT;
                CREATE INDEX IF NOT EXISTS requests_address_key_idx ON requests(address_key);
                CREATE INDEX IF NOT EXISTS requests_requester_ip_idx ON requests(requester_ip);
                """
            )
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version in (0, 1):
                columns = {row[1] for row in connection.execute("PRAGMA table_info(requests)")}
                if "funded_at" not in columns:
                    # Legacy created_at is reservation time, not completion.
                    # Existing requests remain replayable without a guessed clock.
                    connection.execute("ALTER TABLE requests ADD COLUMN funded_at REAL")
                connection.execute(f"PRAGMA user_version = {_DATABASE_VERSION}")
            elif version != _DATABASE_VERSION:
                raise StateError("unsupported faucet database version")
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise StateError("faucet database integrity check failed")
            self._connection = connection
            self.path.chmod(0o600)
        except StateError:
            if "connection" in locals():
                connection.close()
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            if "connection" in locals():
                connection.close()
            raise StateError("faucet database is unavailable or corrupt") from exc

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "FundingState":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def metadata(self, key: str) -> Optional[str]:
        try:
            row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise StateError("cannot read faucet metadata") from exc
        return None if row is None else str(row[0])

    def set_metadata(self, key: str, value: str) -> None:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self.connection.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            self._rollback()
            raise StateError("cannot persist faucet metadata") from exc

    def chain_checkpoint(self) -> Optional[tuple[int, str]]:
        encoded = self.metadata("chainCheckpoint")
        if encoded is None:
            return None
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise StateError("chain checkpoint is corrupt") from exc
        if (
            not isinstance(value, dict)
            or frozenset(value) != frozenset({"blockNumber", "blockHash"})
            or not isinstance(value.get("blockNumber"), int)
            or isinstance(value.get("blockNumber"), bool)
            or int(value["blockNumber"]) <= 0
            or not isinstance(value.get("blockHash"), str)
            or re.fullmatch(r"0x[0-9a-f]{64}", value["blockHash"]) is None
        ):
            raise StateError("chain checkpoint is corrupt")
        return int(value["blockNumber"]), value["blockHash"]

    def set_chain_checkpoint(self, checkpoint: tuple[int, str]) -> None:
        block_number, block_hash = checkpoint
        if block_number <= 0 or re.fullmatch(r"0x[0-9a-f]{64}", block_hash) is None:
            raise StateError("chain checkpoint is invalid")
        self.set_metadata(
            "chainCheckpoint",
            json.dumps(
                {"blockNumber": block_number, "blockHash": block_hash},
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

    def recover_uncertain(self) -> int:
        try:
            cursor = self.connection.execute(
                "UPDATE requests SET status = 'uncertain', http_status = 409, "
                "error_code = 'REQUEST_UNCERTAIN', error_reason = 'request outcome is uncertain and will not be replayed' "
                "WHERE status = 'reserved'"
            )
            return int(cursor.rowcount)
        except sqlite3.DatabaseError as exc:
            raise StateError("cannot recover incomplete faucet reservations") from exc

    def lookup(self, request: FundingRequest) -> Optional[Reservation]:
        try:
            existing = self.connection.execute(
                "SELECT address_key, status, http_status, error_code, error_reason, result_json "
                "FROM requests WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise StateError("cannot read faucet request state") from exc
        if existing is None:
            return None
        if existing["address_key"] != request.address_key:
            return Reservation(kind="conflict")
        result = None
        if existing["result_json"] is not None:
            try:
                loaded = json.loads(existing["result_json"])
            except json.JSONDecodeError as exc:
                raise StateError("stored faucet result is invalid") from exc
            if not isinstance(loaded, dict):
                raise StateError("stored faucet result is invalid")
            result = loaded
        return Reservation(
            kind="existing",
            status=existing["status"],
            result=result,
            http_status=existing["http_status"],
            error_code=existing["error_code"],
            error_reason=existing["error_reason"],
        )

    def reserve(self, request: FundingRequest, now: Optional[float] = None, *, needs_top_up: bool = True) -> Reservation:
        timestamp = self.now() if now is None else now
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT address_key, status, http_status, error_code, error_reason, result_json "
                "FROM requests WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()
            if existing is not None:
                self.connection.execute("COMMIT")
                if existing["address_key"] != request.address_key:
                    return Reservation(kind="conflict")
                result = None
                if existing["result_json"] is not None:
                    loaded = json.loads(existing["result_json"])
                    if not isinstance(loaded, dict):
                        raise StateError("stored faucet result is invalid")
                    result = loaded
                return Reservation(
                    kind="existing",
                    status=existing["status"],
                    result=result,
                    http_status=existing["http_status"],
                    error_code=existing["error_code"],
                    error_reason=existing["error_reason"],
                )

            if needs_top_up:
                last_funded = self.connection.execute(
                    "SELECT MAX(funded_at) FROM requests WHERE address_key = ? AND status = 'completed'",
                    (request.address_key,),
                ).fetchone()[0]
                remaining = 0 if last_funded is None else last_funded + COOLDOWN_SECONDS - timestamp
                if remaining > 0:
                    self.connection.execute("COMMIT")
                    return Reservation(kind="cooldown", retry_after_seconds=math.ceil(remaining))
            self.connection.execute(
                "INSERT INTO requests(request_id, address_key, requester_ip, created_at, status) "
                "VALUES (?, ?, ?, ?, 'reserved')",
                (request.request_id, request.address_key, request.requester_ip, int(timestamp)),
            )
            self.connection.execute("COMMIT")
            return Reservation(kind="reserved")
        except StateError:
            self._rollback()
            raise
        except (json.JSONDecodeError, sqlite3.DatabaseError) as exc:
            self._rollback()
            raise StateError("cannot reserve faucet request") from exc

    def complete(self, request_id: str, result: Mapping[str, object], *, did_transfer: bool = False) -> None:
        encoded = json.dumps(dict(result), allow_nan=False, separators=(",", ":"), sort_keys=True)
        self._transition(
            request_id,
            status="completed",
            http_status=200,
            error_code=None,
            error_reason=None,
            result_json=encoded,
            funded_at=self.now() if did_transfer else None,
        )

    def fail(self, request_id: str) -> None:
        self._transition(
            request_id,
            status="failed",
            http_status=502,
            error_code="FUNDING_FAILED",
            error_reason="funding could not be completed",
            result_json=None,
        )

    def uncertain(self, request_id: str) -> None:
        self._transition(
            request_id,
            status="uncertain",
            http_status=409,
            error_code="REQUEST_UNCERTAIN",
            error_reason="request outcome is uncertain and will not be replayed",
            result_json=None,
        )

    def _transition(
        self,
        request_id: str,
        *,
        status: str,
        http_status: int,
        error_code: Optional[str],
        error_reason: Optional[str],
        result_json: Optional[str],
        funded_at: Optional[float] = None,
    ) -> None:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            cursor = self.connection.execute(
                "UPDATE requests SET status = ?, http_status = ?, error_code = ?, error_reason = ?, "
                "result_json = ?, funded_at = ? WHERE request_id = ? AND status = 'reserved'",
                (status, http_status, error_code, error_reason, result_json, funded_at, request_id),
            )
            if cursor.rowcount != 1:
                raise StateError("faucet request is not in the reserved state")
            self.connection.execute("COMMIT")
        except StateError:
            self._rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self._rollback()
            raise StateError("cannot persist faucet request outcome") from exc

    def _rollback(self) -> None:
        try:
            self.connection.execute("ROLLBACK")
        except sqlite3.DatabaseError:
            pass

