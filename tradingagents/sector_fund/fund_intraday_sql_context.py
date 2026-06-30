from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml


@dataclass
class FieldRow:
    entity_type: str
    entity_code: str
    entity_name: str
    field_name: str
    value: Any
    source: str
    source_status: str
    audit_status: str = ""
    final_source: str = ""
    raw_text_path: str = ""
    include_in_llm: bool = True


@dataclass
class FundDecisionContext:
    config_file: str
    db_path: str
    trade_date: str
    decision_time: str
    portfolio: Dict[str, Any]
    funds: List[Dict[str, Any]]
    snapshot: Dict[str, Any] = field(default_factory=dict)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    field_rows: List[FieldRow] = field(default_factory=list)
    data_source_runs: List[Dict[str, Any]] = field(default_factory=list)
    latest_snapshot_id: int | None = None
    core_coverage_rate: float = 0.0
    all_coverage_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_file": self.config_file,
            "db_path": self.db_path,
            "trade_date": self.trade_date,
            "decision_time": self.decision_time,
            "portfolio": self.portfolio,
            "funds": self.funds,
            "snapshot": self.snapshot,
            "diagnostics": self.diagnostics,
            "field_rows": [row.__dict__ for row in self.field_rows],
            "data_source_runs": self.data_source_runs,
            "latest_snapshot_id": self.latest_snapshot_id,
            "core_coverage_rate": self.core_coverage_rate,
            "all_coverage_rate": self.all_coverage_rate,
        }


def load_fund_decision_context(
    config_path: str | Path,
    db_path: str | Path | None = None,
    decision_time: str = "1445",
    snapshot: Dict[str, Any] | None = None,
) -> FundDecisionContext:
    config_path = str(config_path)
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    resolved_db_path = str(db_path or config.get("database", {}).get("path") or "data/fund_assistant.sqlite3")
    loaded_snapshot = snapshot or {}
    diagnostics: Dict[str, Any] = {}
    snapshot_id: int | None = None

    if Path(resolved_db_path).exists():
        with sqlite3.connect(resolved_db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = _latest_snapshot_row(conn, decision_time)
            if row:
                snapshot_id = int(row["id"])
                loaded_snapshot = _json_load(row["snapshot_json"]) or loaded_snapshot
                diagnostics = _json_load(row["diagnostics_json"])
                core_coverage = _num(row["core_coverage_rate"])
                all_coverage = _num(row["all_coverage_rate"])
            else:
                core_coverage = _num(loaded_snapshot.get("core_coverage_rate"))
                all_coverage = _num(loaded_snapshot.get("all_coverage_rate"))
            field_rows = _load_field_rows(conn, snapshot_id=snapshot_id, fallback_snapshot=loaded_snapshot)
            source_runs = _load_source_runs(conn)
    else:
        core_coverage = _num(loaded_snapshot.get("core_coverage_rate"))
        all_coverage = _num(loaded_snapshot.get("all_coverage_rate"))
        field_rows = _flatten_snapshot_fields(loaded_snapshot)
        source_runs = []

    return FundDecisionContext(
        config_file=config_path,
        db_path=resolved_db_path,
        trade_date=str(loaded_snapshot.get("trade_date") or date.today().isoformat()),
        decision_time=decision_time,
        portfolio=config.get("portfolio", {}),
        funds=config.get("funds", []),
        snapshot=loaded_snapshot,
        diagnostics=diagnostics,
        field_rows=field_rows,
        data_source_runs=source_runs,
        latest_snapshot_id=snapshot_id,
        core_coverage_rate=core_coverage,
        all_coverage_rate=all_coverage,
    )


def render_field_table(rows: Iterable[FieldRow], limit: int | None = None) -> str:
    lines = ["| 实体 | 字段 | 值 | 来源 | 状态 | 最终源 | 进入LLM |", "| --- | --- | --- | --- | --- | --- | --- |"]
    selected = list(rows)
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        lines.append("| - | - | - | - | - | - | - |")
        return "\n".join(lines)
    for row in selected:
        entity = f"{row.entity_type}:{row.entity_name or row.entity_code}".strip(":")
        value = _short(row.value)
        lines.append(
            f"| {_md(entity)} | {_md(row.field_name)} | {_md(value)} | {_md(row.source)} | "
            f"{_md(row.audit_status or row.source_status)} | {_md(row.final_source)} | {'yes' if row.include_in_llm else 'no'} |"
        )
    return "\n".join(lines)


def _latest_snapshot_row(conn: sqlite3.Connection, decision_time: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM intraday_snapshot
        WHERE decision_time=?
        ORDER BY trade_date DESC, updated_at DESC, id DESC
        LIMIT 1
        """,
        (decision_time,),
    ).fetchone()


def _load_field_rows(conn: sqlite3.Connection, snapshot_id: int | None, fallback_snapshot: Dict[str, Any]) -> List[FieldRow]:
    rows: List[sqlite3.Row] = []
    if snapshot_id is not None:
        rows = conn.execute("SELECT * FROM field_source WHERE snapshot_id=? ORDER BY entity_type, entity_code, field_name", (snapshot_id,)).fetchall()
    if not rows:
        latest_run = conn.execute("SELECT run_id FROM field_source WHERE run_id IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        if latest_run:
            rows = conn.execute("SELECT * FROM field_source WHERE run_id=? ORDER BY entity_type, entity_code, field_name", (latest_run["run_id"],)).fetchall()
    if rows:
        return [_field_row_from_sql(row) for row in rows]
    return _flatten_snapshot_fields(fallback_snapshot)


def _field_row_from_sql(row: sqlite3.Row) -> FieldRow:
    value = row["value_text"] if "value_text" in row.keys() else ""
    return FieldRow(
        entity_type=str(row["entity_type"] or ""),
        entity_code=str(row["entity_code"] or ""),
        entity_name=str(row["entity_name"] if "entity_name" in row.keys() else "" or ""),
        field_name=str(row["field_name"] or ""),
        value=value,
        source=str(row["source"] or ""),
        source_status=str(row["source_status"] or ""),
        audit_status=str(row["audit_status"] if "audit_status" in row.keys() else "" or ""),
        final_source=str(row["final_source"] if "final_source" in row.keys() else "" or ""),
        raw_text_path=str(row["raw_text_path"] if "raw_text_path" in row.keys() else "" or ""),
        include_in_llm=True,
    )


def _load_source_runs(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM data_source_run ORDER BY id DESC LIMIT 80").fetchall()
    return [dict(row) for row in rows]


def _flatten_snapshot_fields(snapshot: Dict[str, Any]) -> List[FieldRow]:
    rows: List[FieldRow] = []

    def walk(prefix: str, value: Any, entity_type: str = "snapshot", entity_code: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                walk(next_prefix, child, entity_type=entity_type, entity_code=entity_code)
        elif isinstance(value, list):
            rows.append(FieldRow(entity_type, entity_code, "", prefix, value, "snapshot", "present"))
        else:
            rows.append(FieldRow(entity_type, entity_code, "", prefix, value, "snapshot", "present"))

    walk("", snapshot)
    return rows


def _json_load(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _short(value: Any, limit: int = 120) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("|", "/")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _md(value: Any) -> str:
    return _short(value).replace("|", "\\|")
