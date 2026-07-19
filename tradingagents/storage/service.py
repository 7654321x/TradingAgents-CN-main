from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_engine, init_db
from .models import Instrument, FundHoldingReport, FundHoldingPosition, FundInstrumentRelation, Universe, UniverseInstrument
from tradingagents.extensions.sector_fund import load_fund_holdings_seed

def ingest_fund_holdings(seed_path=None, engine=None) -> dict[str,int]:
    seed=load_fund_holdings_seed(seed_path); engine=init_db(engine); counts={"funds":0,"stocks":0,"etfs":0,"reports":0,"positions":0,"relations":0}
    with Session(engine) as session:
        def instrument(item, typ):
            obj=session.scalar(select(Instrument).where(Instrument.symbol==item["symbol"]))
            if not obj: obj=Instrument(symbol=item["symbol"],local_code=item.get("local_code"),name=item.get("name"),instrument_type=typ); session.add(obj); session.flush()
            return obj
        for fund in seed["funds"]:
            f=instrument({"symbol":"FUND:"+fund["fund_code"],"local_code":fund["fund_code"],"name":fund["fund_name"]},"fund"); counts["funds"]+=1
            report=session.scalar(select(FundHoldingReport).where(FundHoldingReport.fund_instrument_id==f.id,FundHoldingReport.report_period_end==fund["report_period_end"]))
            if report is None:
                report=FundHoldingReport(fund_instrument_id=f.id,report_period_end=fund["report_period_end"],published_date=fund["published_date"],holdings_count=len(fund["holdings"])); session.add(report); session.flush(); counts["reports"]+=1
            else:
                pass
            for h in fund["holdings"]:
                stock=instrument(h,"stock")
                if not session.scalar(select(FundHoldingPosition).where(FundHoldingPosition.report_id==report.id,FundHoldingPosition.stock_instrument_id==stock.id)):
                    session.add(FundHoldingPosition(report_id=report.id,stock_instrument_id=stock.id,rank=h["rank"],weight_pct=h.get("weight_pct"))); counts["positions"]+=1
            proxy=fund.get("proxy_instrument")
            if proxy:
                etf=instrument(proxy,"etf"); session.add(FundInstrumentRelation(fund_instrument_id=f.id,related_instrument_id=etf.id,relationship_type=proxy.get("relationship_type","target_etf"),weight_pct=proxy.get("weight_pct"),report_period_end=fund["report_period_end"],published_date=fund["published_date"])); counts["relations"]+=1
        session.commit()
        counts["stocks"]=session.scalar(select(Instrument).where(Instrument.instrument_type=="stock").count()) if False else len({h["symbol"] for f in seed["funds"] for h in f["holdings"]})
        counts["etfs"]=sum(1 for f in seed["funds"] if f.get("proxy_instrument"))
        universe=session.scalar(select(Universe).where(Universe.code=="fund_holdings_2026q1"))
        if not universe:
            universe=Universe(code="fund_holdings_2026q1",name="2026 Q1 fund holdings",universe_type="fund_holdings",as_of_date=seed.get("as_of_date")); session.add(universe); session.flush()
        for symbol in [h["symbol"] for f in seed["funds"] for h in f["holdings"]] + [f["proxy_instrument"]["symbol"] for f in seed["funds"] if f.get("proxy_instrument")]:
            inst=session.scalar(select(Instrument).where(Instrument.symbol==symbol));
            if not session.scalar(select(UniverseInstrument).where(UniverseInstrument.universe_id==universe.id,UniverseInstrument.instrument_id==inst.id)): session.add(UniverseInstrument(universe_id=universe.id,instrument_id=inst.id,membership_type="target_etf" if inst.instrument_type=="etf" else "holding_stock",source="fund_seed"))
        manual=session.scalar(select(Universe).where(Universe.code=="manual_test"))
        if not manual: manual=Universe(code="manual_test",name="Manual test universe",universe_type="test"); session.add(manual); session.flush()
        for symbol in ("600519.SS","300750.SZ"):
            inst=session.scalar(select(Instrument).where(Instrument.symbol==symbol))
            if not inst: inst=Instrument(symbol=symbol,local_code=symbol[:-3],name=symbol,instrument_type="stock"); session.add(inst); session.flush()
            if not session.scalar(select(UniverseInstrument).where(UniverseInstrument.universe_id==manual.id,UniverseInstrument.instrument_id==inst.id)): session.add(UniverseInstrument(universe_id=manual.id,instrument_id=inst.id,membership_type="manual_test",source="cli"))
        session.commit()
    return counts
