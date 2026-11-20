"""Persistence primitives for the knowledge base + agent config (ADR-032).

`Store` is a tiny table-oriented interface so the services stay unit-testable: `MemoryStore` for
tests, `PgStore` (psycopg, schema `app`) at runtime. Service code always passes `organization_id`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

EXPLAIN_TABLES = {"explain_session", "statement_version", "assessment_round", "explain_turn", "help_request", "vh_feedback"}
TABLES = {"kb_object", "agent_config", "agent_config_history", "kb_policy_document", "kb_proposal"} | EXPLAIN_TABLES
UPDATED_AT_TABLES = ("kb_object", "agent_config", "explain_session", "help_request")
JSON_COLUMNS: dict[str, set[str]] = {
    "kb_object": {"scope", "body", "replay", "history"},
    "agent_config": {"value"},
    "agent_config_history": {"old_value", "new_value"},
    "kb_policy_document": set(),
    "kb_proposal": {"payload"},
    "explain_session": {"form_schema", "answers", "plan", "memory", "provenance", "open_points"},
    "statement_version": {"content"},
    "assessment_round": {"matched_evidence", "contradictions", "open_points", "missing_internal", "suggested_questions",
                         "motive", "provenance"},
    "explain_turn": {"payload"},
    "help_request": {"facts", "options", "reply_facts"},
    "vh_feedback": {"error_types"},
}
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _now() -> datetime:
    return datetime.now(UTC)


class Store(Protocol):
    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]: ...
    def get(self, table: str, row_id: str) -> dict[str, Any] | None: ...
    def find(self, table: str, where: dict[str, Any] | None = None, order: str | None = None,
             limit: int | None = None) -> list[dict[str, Any]]: ...
    def update(self, table: str, row_id: str, patch: dict[str, Any],
               where: dict[str, Any] | None = None) -> dict[str, Any] | None: ...
    def audit(self, organization_id: str, actor_id: str | None, action: str, payload: dict[str, Any],
              result: str = "accepted") -> None: ...
    def principal_name(self, principal_id: str) -> str | None: ...
    def case_params(self, organization_id: str, case_ids: list[str] | None = None, limit: int = 30) -> list[dict[str, Any]]: ...
    def case_info(self, organization_id: str, case_id: str) -> dict[str, Any] | None: ...


class MemoryStore:
    def __init__(self, cases: list[dict[str, Any]] | None = None):
        self.tables: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in TABLES}
        self.audit_log: list[dict[str, Any]] = []
        self.cases = cases or []
        self._clock = 0

    def _stamp(self) -> datetime:
        self._clock += 1  # strictly increasing so ordering by created_at is deterministic
        return datetime(2026, 11, 20, tzinfo=UTC).replace(microsecond=self._clock)

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        r = copy.deepcopy(row)
        r.setdefault("id", str(uuid.uuid4()))
        r.setdefault("created_at", self._stamp())
        if table in UPDATED_AT_TABLES:
            r.setdefault("updated_at", r["created_at"])
        if table == "kb_object":
            for t in self.tables["kb_object"].values():
                if (t["organization_id"], t["type"], t["code"], t["version"]) == (r["organization_id"], r["type"], r["code"], r["version"]):
                    raise ValueError("duplicate kb_object version")
        self.tables[table][r["id"]] = r
        return copy.deepcopy(r)

    def get(self, table: str, row_id: str) -> dict[str, Any] | None:
        r = self.tables[table].get(str(row_id))
        return copy.deepcopy(r) if r else None

    @staticmethod
    def _match(row: dict[str, Any], where: dict[str, Any]) -> bool:
        for k, v in where.items():
            if isinstance(v, (list, tuple, set)):
                if row.get(k) not in v:
                    return False
            elif row.get(k) != v:
                return False
        return True

    def find(self, table: str, where: dict[str, Any] | None = None, order: str | None = None,
             limit: int | None = None) -> list[dict[str, Any]]:
        rows = [r for r in self.tables[table].values() if self._match(r, where or {})]
        for spec in reversed([s.strip() for s in (order or "").split(",") if s.strip()]):
            col, _, direction = spec.partition(" ")
            rows.sort(key=lambda r, c=col: (r.get(c) is None, r.get(c)), reverse=direction.lower() == "desc")
        return copy.deepcopy(rows[:limit] if limit else rows)

    def update(self, table: str, row_id: str, patch: dict[str, Any], where: dict[str, Any] | None = None) -> dict[str, Any] | None:
        r = self.tables[table].get(str(row_id))
        if r is None or not self._match(r, where or {}):
            return None
        r.update(copy.deepcopy(patch))
        if "updated_at" in r or table in UPDATED_AT_TABLES:
            r["updated_at"] = self._stamp()
        return copy.deepcopy(r)

    def audit(self, organization_id: str, actor_id: str | None, action: str, payload: dict[str, Any],
              result: str = "accepted") -> None:
        self.audit_log.append({"organization_id": organization_id, "actor_id": actor_id, "action": action,
                               "payload": payload, "result": result})

    def principal_name(self, principal_id: str) -> str | None:
        return None

    def case_params(self, organization_id: str, case_ids: list[str] | None = None, limit: int = 30) -> list[dict[str, Any]]:
        rows = [c for c in self.cases if not case_ids or c["case_id"] in case_ids]
        return copy.deepcopy(rows[:limit])

    def case_info(self, organization_id: str, case_id: str) -> dict[str, Any] | None:
        for c in self.cases:
            if c["case_id"] == case_id and c.get("organization_id", organization_id) == organization_id:
                return {"case_id": case_id, "organization_id": organization_id, "driver_id": c.get("driver_id"),
                        "status": c.get("status", "evidence_requested"), "category": c.get("category")}
        return None


def _norm(v: Any) -> Any:
    return str(v) if isinstance(v, uuid.UUID) else v


class PgStore:
    """psycopg-backed store; one short-lived connection per call."""

    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    @staticmethod
    def _check(table: str, *cols: str) -> None:
        if table not in TABLES:
            raise ValueError(f"unknown table {table}")
        for c in cols:
            if not _IDENT.match(c):
                raise ValueError(f"bad column {c}")

    def _adapt(self, table: str, col: str, val: Any) -> Any:
        if col in JSON_COLUMNS[table] and val is not None:
            from psycopg.types.json import Jsonb

            return Jsonb(val)
        return val

    def _row(self, r: dict[str, Any] | None) -> dict[str, Any] | None:
        return {k: _norm(v) for k, v in r.items()} if r else None

    def _where(self, table: str, where: dict[str, Any] | None) -> tuple[str, list[Any]]:
        clauses, params = [], []
        for k, v in (where or {}).items():
            self._check(table, k)
            if isinstance(v, (list, tuple, set)):
                clauses.append(f"{k}::text = ANY(%s)")
                params.append([str(x) for x in v])
            elif v is None:
                clauses.append(f"{k} IS NULL")
            else:
                clauses.append(f"{k}::text = %s" if k.endswith("_id") or k == "id" else f"{k} = %s")
                params.append(str(v) if k.endswith("_id") or k == "id" else self._adapt(table, k, v))
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        self._check(table, *row)
        cols = list(row)
        sql = f"INSERT INTO app.{table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING *"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, [self._adapt(table, c, row[c]) for c in cols])
            out = cur.fetchone()
            conn.commit()
        return self._row(out)  # type: ignore[return-value]

    def get(self, table: str, row_id: str) -> dict[str, Any] | None:
        self._check(table)
        if not _UUID.match(str(row_id)):
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT * FROM app.{table} WHERE id = %s::uuid", (str(row_id),))
            return self._row(cur.fetchone())

    def find(self, table: str, where: dict[str, Any] | None = None, order: str | None = None,
             limit: int | None = None) -> list[dict[str, Any]]:
        self._check(table)
        w, params = self._where(table, where)
        sql = f"SELECT * FROM app.{table}{w}"
        if order:
            parts = []
            for spec in order.split(","):
                col, _, d = spec.strip().partition(" ")
                self._check(table, col)
                parts.append(f"{col} {'DESC' if d.lower() == 'desc' else 'ASC'}")
            sql += " ORDER BY " + ", ".join(parts)
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [self._row(r) for r in cur.fetchall()]  # type: ignore[misc]

    def update(self, table: str, row_id: str, patch: dict[str, Any], where: dict[str, Any] | None = None) -> dict[str, Any] | None:
        self._check(table, *patch)
        sets = [f"{c} = %s" for c in patch]
        vals = [self._adapt(table, c, v) for c, v in patch.items()]
        if table in UPDATED_AT_TABLES and "updated_at" not in patch:
            sets.append("updated_at = now()")
        w, wparams = self._where(table, where)
        sql = f"UPDATE app.{table} SET {', '.join(sets)} WHERE id = %s::uuid" + (w.replace(" WHERE ", " AND ") if w else "") + " RETURNING *"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, [*vals, str(row_id), *wparams])
            out = cur.fetchone()
            conn.commit()
        return self._row(out)

    def audit(self, organization_id: str, actor_id: str | None, action: str, payload: dict[str, Any],
              result: str = "accepted") -> None:
        text = json.dumps(payload, default=str)
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO app.audit_events (event_id, organization_id, actor_id, case_id, action, result,
                       request_id, redacted_payload, previous_hash, event_hash)
                   VALUES (gen_random_uuid(), %s::uuid, %s::uuid, NULL, %s, %s, gen_random_uuid(), %s::jsonb, '\\x'::bytea, %s)""",
                (organization_id, actor_id, action, result, text, digest),
            )
            conn.commit()

    def principal_name(self, principal_id: str) -> str | None:
        if not _UUID.match(str(principal_id)):
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT display_name FROM app.principals WHERE id = %s::uuid", (str(principal_id),))
            r = cur.fetchone()
            return r["display_name"] if r else None

    def case_info(self, organization_id: str, case_id: str) -> dict[str, Any] | None:
        if not _UUID.match(str(case_id)):
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT fc.id::text AS case_id, fc.organization_id::text AS organization_id, fc.status,
                          fc.suspected_category AS category, ta.driver_id::text AS driver_id
                     FROM app.fraud_cases fc LEFT JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
                    WHERE fc.id = %s::uuid AND fc.organization_id = %s::uuid""",
                (str(case_id), str(organization_id)))
            return self._row(cur.fetchone())

    def case_params(self, organization_id: str, case_ids: list[str] | None = None, limit: int = 30) -> list[dict[str, Any]]:
        """Best-effort parameter values for real cases (fare, duration, trips today, feature-set signals)."""
        sql = """
        SELECT fc.id::text AS case_id, t.fare_amount_vnd AS fare_vnd,
               EXTRACT(EPOCH FROM (ta.ended_at - ta.started_at)) / 60.0 AS trip_duration_min,
               (SELECT count(*) FROM app.trip_assignments o
                 WHERE o.driver_id = ta.driver_id AND o.started_at::date = ta.started_at::date
                   AND o.started_at < ta.started_at) AS trips_today,
               fs.features AS features
          FROM app.fraud_cases fc
          JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
          JOIN app.trips t ON t.id = ta.trip_id
          LEFT JOIN LATERAL (
              SELECT f.features FROM app.evidence_snapshots es JOIN app.feature_sets f ON f.evidence_snapshot_id = es.id
               WHERE es.case_id = fc.id ORDER BY f.created_at DESC LIMIT 1) fs ON true
         WHERE fc.organization_id = %s::uuid"""
        params: list[Any] = [organization_id]
        if case_ids:
            sql += " AND fc.id::text = ANY(%s)"
            params.append([str(c) for c in case_ids])
        sql += " ORDER BY fc.created_at DESC LIMIT %s"
        params.append(int(limit))
        out = []
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            for r in cur.fetchall():
                feats = r["features"] or {}
                vals: dict[str, Any] = {
                    "fare_vnd": r["fare_vnd"],
                    "trip_duration_min": float(r["trip_duration_min"]) if r["trip_duration_min"] is not None else None,
                    "trips_today": int(r["trips_today"]) if r["trips_today"] is not None else None,
                    "stationary_duration_s": feats.get("stationary_duration_s"),
                    "davi": feats.get("davi"),
                    "distance_to_pickup_m": feats.get("distance_to_pickup_start_m"),
                }
                out.append({"case_id": r["case_id"], "params": {k: v for k, v in vals.items() if v is not None}})
        return out


def default_store() -> Store:
    """Runtime store from settings.database_url; raises 503 when no database is configured."""
    import psycopg
    from fastapi import HTTPException
    from psycopg.rows import dict_row

    from src.config import get_settings

    url = get_settings().database_url
    if not url:
        raise HTTPException(503, "Database unavailable")

    def connect():
        return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)

    return PgStore(connect)
