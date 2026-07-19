from __future__ import annotations
import hashlib, json, time, uuid
from datetime import datetime, timezone, time as dtime
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import init_db
from .models import Instrument, MarketBarObservation, IngestionRun, IngestionRunItem
from tradingagents.extensions.sector_fund import ALL_MARKET_SYMBOLS

SH=ZoneInfo("Asia/Shanghai")
PRICE_COLUMNS = ["Open", "High", "Low", "Close"]
def clean_ticker_frame(frame: pd.DataFrame, interval: str = "1d") -> tuple[pd.DataFrame, dict[str,int]]:
    stats={"raw_row_count":len(frame),"all_null_rows_removed":0,"partial_ohlc_rows_removed":0,"out_of_session_rows_removed":0}
    if frame.empty:return frame.copy(),stats
    missing=[c for c in PRICE_COLUMNS if c not in frame.columns]
    if missing: raise ValueError(f"Missing required OHLC columns: {missing}")
    all_null=frame[PRICE_COLUMNS].isna().all(axis=1); stats["all_null_rows_removed"]=int(all_null.sum()); frame=frame.loc[~all_null].copy()
    partial=frame[PRICE_COLUMNS].isna().any(axis=1); stats["partial_ohlc_rows_removed"]=int(partial.sum()); frame=frame.loc[~partial].copy()
    if interval=="5m":
        idx=pd.DatetimeIndex(frame.index); local=idx.tz_localize(SH) if idx.tz is None else idx.tz_convert(SH); t=local.time
        valid=((pd.Series(t,index=frame.index)>=dtime(9,30))&(pd.Series(t,index=frame.index)<=dtime(11,30)))|((pd.Series(t,index=frame.index)>=dtime(13,0))&(pd.Series(t,index=frame.index)<=dtime(15,0)))
        stats["out_of_session_rows_removed"]=int((~valid).sum()); frame=frame.loc[valid.to_numpy()].copy()
    return frame,stats
def market_phase(now=None):
    now=(now or datetime.now(SH)).astimezone(SH); t=now.time()
    if now.weekday()>=5:return "non_trading_day"
    if t<dtime(9,30):return "pre_market"
    if t<dtime(11,30):return "morning_session"
    if t<dtime(13,0):return "lunch_break"
    if t<dtime(15,0):return "afternoon_session"
    return "after_close"
def _frame(data,symbol):
    if data is None or data.empty:return pd.DataFrame()
    if isinstance(data.columns,pd.MultiIndex):
        if symbol in data.columns.get_level_values(0):return data[symbol]
        if symbol in data.columns.get_level_values(1):return data.xs(symbol,axis=1,level=1)
    return data
def _utc(v):
    ts=pd.Timestamp(v)
    if ts.tzinfo is None: ts=ts.tz_localize(SH)
    return ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)
def _hash(row): return hashlib.sha256(json.dumps({k:(None if pd.isna(row.get(k)) else str(row.get(k))) for k in row.index},sort_keys=True).encode()).hexdigest()
def ingest_market(symbols=None, interval="1d", period="1mo", engine=None, max_retries=3):
    engine=init_db(engine); symbols=tuple(symbols or ALL_MARKET_SYMBOLS); run_id=uuid.uuid4().hex; started=datetime.utcnow(); now=datetime.now(timezone.utc);
    with Session(engine) as s: s.add(IngestionRun(run_id=run_id,started_at=started,provider="yfinance",requested_symbols=len(symbols),status="RUNNING",yfinance_version=yf.__version__,schema_version="1.0")); s.commit()
    kwargs=dict(tickers=list(symbols),period=period,interval=interval,group_by="ticker",auto_adjust=False,actions=interval=="1d",repair=True,threads=True,progress=False,timeout=20)
    try: batch=yf.download(**kwargs)
    except Exception: batch=pd.DataFrame()
    successes=failures=0
    for symbol in symbols:
        started_item=time.perf_counter(); frame=_frame(batch,symbol); error=None
        if frame.empty:
            for attempt in range(max_retries):
                try:
                    frame=yf.Ticker(symbol).history(period=period,interval=interval,auto_adjust=False,actions=interval=="1d",repair=True,timeout=20)
                    if not frame.empty: break
                except Exception as exc: error=exc
                time.sleep(2**attempt)
        inserted=skipped=0
        try:
            with Session(engine) as s:
                inst=s.scalar(select(Instrument).where(Instrument.symbol==symbol))
                if not inst:
                    suffix = ".SS" if symbol.endswith(".SS") else ".SZ" if symbol.endswith(".SZ") else ""
                    if not suffix: raise ValueError(f"instrument missing: {symbol}")
                    inst = Instrument(symbol=symbol, local_code=symbol[:-3], name=symbol, instrument_type="etf" if symbol == "589130.SS" else "stock", exchange=suffix[1:], currency="CNY", timezone="Asia/Shanghai")
                    s.add(inst); s.flush()
                if frame.empty: raise ValueError(error or "no data")
                frame, quality = clean_ticker_frame(frame, interval)
                if frame.empty: raise ValueError("no valid OHLC rows after cleaning")
                cols={str(c).lower().replace(" ","_"):c for c in frame.columns}; required=["open","high","low","close","volume"]
                missing=[x for x in required if x not in cols]
                for idx,row in frame.iterrows():
                    payload=_hash(row); bt=_utc(idx); final=interval=="1d" and (bt.date()<datetime.now(SH).date() or market_phase()=="after_close") or interval=="5m" and (pd.Timestamp(idx).tz_convert(SH).date()<datetime.now(SH).date() or pd.Timestamp(idx).tz_convert(SH).time()<dtime(15,0))
                    if s.scalar(select(MarketBarObservation.id).where(MarketBarObservation.instrument_id==inst.id,MarketBarObservation.interval==interval,MarketBarObservation.bar_time==bt,MarketBarObservation.provider=="yfinance",MarketBarObservation.payload_hash==payload)): skipped+=1; continue
                    get=lambda n: float(row[cols[n]]) if n in cols and pd.notna(row[cols[n]]) else None
                    local_ts=pd.Timestamp(idx); local_ts=local_ts.tz_localize(SH) if local_ts.tzinfo is None else local_ts.tz_convert(SH)
                    s.add(MarketBarObservation(instrument_id=inst.id,interval=interval,bar_time=bt,market_date=local_ts.date().isoformat() if interval=="1d" else None,open=get("open"),high=get("high"),low=get("low"),close=get("close"),adjusted_close=get("adj_close"),volume=get("volume"),dividends=get("dividends"),stock_splits=get("stock_splits"),capital_gains=get("capital_gains"),is_final=final,provider="yfinance",upstream_group="yahoo_finance",source_event_time=bt,available_at=now.replace(tzinfo=None),fetched_at=now.replace(tzinfo=None),payload_hash=payload,run_id=run_id)); inserted+=1
                quality.update(valid_row_count=len(frame),inserted_count=inserted,duplicate_payload_rows_skipped=skipped)
                s.add(IngestionRunItem(run_id=run_id,symbol=symbol,dataset_type="daily" if interval=="1d" else "intraday_5m",status="PARTIAL" if missing else ("SUCCESS_NO_NEW_DATA" if inserted==0 else "SUCCESS"),record_count=len(frame),inserted_count=inserted,skipped_duplicate_count=skipped,first_data_time=str(frame.index[0]),latest_data_time=str(frame.index[-1]),elapsed_ms=int((time.perf_counter()-started_item)*1000),quality_metrics_json=json.dumps(quality,ensure_ascii=False),error_message=("missing columns: "+str(missing)) if missing else None)); s.commit()
            successes+=1
        except Exception as exc:
            failures+=1
            with Session(engine) as s: s.add(IngestionRunItem(run_id=run_id,symbol=symbol,dataset_type="daily" if interval=="1d" else "intraday_5m",status="FAILED",elapsed_ms=int((time.perf_counter()-started_item)*1000),error_type=type(exc).__name__,error_message=str(exc))); s.commit()
    with Session(engine) as s: obj=s.get(IngestionRun,run_id); obj.completed_at=datetime.utcnow(); obj.success_symbols=successes; obj.failed_symbols=failures; obj.status="SUCCESS" if failures==0 else ("PARTIAL" if successes else "FAILED"); s.commit()
    return run_id
