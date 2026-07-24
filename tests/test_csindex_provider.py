from __future__ import annotations

import json
from io import BytesIO

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.baseline import (
    ingest_index_snapshot_failure,
    ingest_official_index_snapshot,
)
from tradingagents.extensions.sector_fund.csindex_provider import fetch_csindex_snapshot
from tradingagents.storage.models import UniverseConstituentWeight, UniverseSnapshot


class _Response:
    def __init__(self, data=None, content=b""):
        self._data = data
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"code": "200", "msg": "Success", "success": True, "data": self._data}


class _Session:
    def get(self, url, **kwargs):
        if "index-basic-info" in url:
            return _Response({"indexCode": "000685", "indexFullNameCn": "上证科创板芯片指数"})
        if "index-feature" in url:
            return _Response({"indexCode": "000685", "tradeDate": "20260722", "consNum": 50.0})
        rows = [
            {
                "日期Date": 20260630,
                "指数代码 Index Code": 685,
                "成份券代码Constituent Code": 688000 + number,
                "成份券名称Constituent Name": f"样本{number}",
                "权重(%)weight": 2.0,
            }
            for number in range(1, 51)
        ]
        output = BytesIO()
        pd.DataFrame(rows).to_excel(output, index=False)
        return _Response(content=output.getvalue())


def test_csindex_provider_loads_complete_official_weight_workbook():
    result = fetch_csindex_snapshot("000685", session=_Session())
    assert result.trade_date == "2026-06-30"
    assert result.membership_trade_date == "2026-07-22"
    assert result.weight_lag_days == 22
    assert result.expected_constituent_count == 50
    assert result.coverage == "FULL"
    assert result.is_complete
    assert result.constituents[0]["symbol"] == "688001.SS"


def test_complete_official_index_snapshot_is_traceable_and_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    snapshot = fetch_csindex_snapshot("000685", session=_Session())
    first = ingest_official_index_snapshot(snapshot, engine=engine)
    second = ingest_official_index_snapshot(snapshot, engine=engine)
    assert first["snapshot_id"] == second["snapshot_id"]

    with Session(engine) as session:
        saved = session.scalar(select(UniverseSnapshot))
        weights = session.scalars(select(UniverseConstituentWeight)).all()
        metadata = json.loads(saved.payload_json)
        assert saved.status == "SUCCESS"
        assert saved.source == "csindex_official"
        assert saved.error_message is None
        assert metadata["universe"]["metadata"]["expected_constituent_count"] == 50
        assert metadata["universe"]["metadata"]["weight_lag_days"] == 22
        assert len(weights) == 50


def test_provider_failure_is_persisted_and_does_not_block_success_source():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    failed = ingest_index_snapshot_failure(
        index_code="000685",
        index_name="上证科创板芯片指数",
        as_of_date="2026-07-22",
        error_message="Timeout: upstream timed out",
        engine=engine,
    )
    success = ingest_official_index_snapshot(
        fetch_csindex_snapshot("000685", session=_Session()), engine=engine
    )
    assert failed["failed_snapshot_id"] != success["snapshot_id"]
    with Session(engine) as session:
        snapshots = session.scalars(select(UniverseSnapshot).order_by(UniverseSnapshot.id)).all()
        assert [item.status for item in snapshots] == ["FAILED", "SUCCESS"]
        assert snapshots[0].error_message == "Timeout: upstream timed out"
