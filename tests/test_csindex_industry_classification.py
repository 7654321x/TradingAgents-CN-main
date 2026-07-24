from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tradingagents.extensions.sector_fund.classification import (
    CHAIN_SCHEME,
    CSI_SCHEME,
    ingest_classification_snapshots,
    load_latest_classifications,
)
from tradingagents.extensions.sector_fund.csindex_industry_provider import (
    fetch_csindex_industry_classifications,
)
from tradingagents.storage.db import init_db
from tradingagents.storage.models import Instrument, InstrumentClassificationSnapshot


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Session:
    def get(self, url, **kwargs):
        return _Response({"code": "200", "success": True, "data": "20260722"})

    def post(self, url, json, **kwargs):
        code = json["searchInput"]
        cics4 = "集成电路设计" if code == "688001" else "未知官方分类"
        return _Response(
            {
                "code": "200",
                "success": True,
                "data": [
                    {
                        "securityCode": code,
                        "securityName": f"股票{code}",
                        "cics1stCode": "45",
                        "cics1stName": "信息技术",
                        "cics2ndCode": "4530",
                        "cics2ndName": "半导体",
                        "cics3rdCode": "453010",
                        "cics3rdName": "集成电路",
                        "cics4thCode": "45301010",
                        "cics4thName": cics4,
                    }
                ],
            }
        )


def test_provider_keeps_official_cics_and_derives_versioned_chain_bucket():
    rows = fetch_csindex_industry_classifications(["688001", "688002"], session=_Session())
    assert rows[0].as_of_date == "2026-07-22"
    assert rows[0].cics4_name == "集成电路设计"
    assert rows[0].supply_chain == "芯片设计"
    assert rows[0].supply_chain_rule == "cics4_rule_v1"
    assert rows[1].cics4_name == "未知官方分类"
    assert rows[1].supply_chain == "未分类"


def test_classification_snapshots_are_idempotent_and_point_in_time():
    engine = init_db(create_engine("sqlite+pysqlite:///:memory:"))
    with Session(engine) as session:
        instruments = [
            Instrument(symbol=f"{code}.SS", local_code=code, name=code, instrument_type="stock")
            for code in ("688001", "688002")
        ]
        session.add_all(instruments)
        session.commit()
        ids = [item.id for item in instruments]
    rows = fetch_csindex_industry_classifications(["688001", "688002"], session=_Session())
    assert ingest_classification_snapshots(rows, engine=engine) == {
        "classification_snapshots_inserted": 4
    }
    assert ingest_classification_snapshots(rows, engine=engine) == {
        "classification_snapshots_inserted": 0
    }
    with Session(engine) as session:
        assert len(session.scalars(select(InstrumentClassificationSnapshot)).all()) == 4
        before = load_latest_classifications(session, ids, "2026-07-21")
        current = load_latest_classifications(session, ids, "2026-07-22")
        assert before == {}
        assert current[ids[0]][CSI_SCHEME]["value"]["level4"]["name"] == "集成电路设计"
        assert current[ids[0]][CHAIN_SCHEME]["value"]["category"] == "芯片设计"
        assert current[ids[1]][CHAIN_SCHEME]["status"] == "PARTIAL"
