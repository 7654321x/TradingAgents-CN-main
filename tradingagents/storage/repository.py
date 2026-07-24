from __future__ import annotations
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .models import Instrument, MarketBarObservation

class MarketBarRepository:
    def __init__(self, session: Session): self.session=session
    def _instrument(self,symbol): return self.session.scalar(select(Instrument).where(Instrument.symbol==symbol))
    def get_latest_bars(self,symbol,interval,start_time=None,end_time=None,include_unfinished=False):
        inst=self._instrument(symbol)
        if not inst:return pd.DataFrame()
        q=select(MarketBarObservation).where(MarketBarObservation.instrument_id==inst.id,MarketBarObservation.interval==interval)
        if interval=="1d":
            if start_time is not None:q=q.where(MarketBarObservation.market_date>=str(start_time)[:10])
            if end_time is not None:q=q.where(MarketBarObservation.market_date<=str(end_time)[:10])
        else:
            if start_time is not None:q=q.where(MarketBarObservation.bar_time>=start_time)
            if end_time is not None:q=q.where(MarketBarObservation.bar_time<=end_time)
        if interval=="1d" and not include_unfinished:q=q.where(MarketBarObservation.is_final.is_(True))
        rows=self.session.scalars(q.order_by(MarketBarObservation.bar_time,MarketBarObservation.fetched_at,MarketBarObservation.id)).all()
        latest={}
        def quality(row):
            """Prefer one complete provider row over a later incomplete row.

            This keeps OHLCV/Amount from a single source and prevents a Yahoo
            row without A-share turnover amount replacing a complete
            AkShare/Eastmoney row for the same trading day.
            """
            ohlcv_complete = all(
                value is not None
                for value in (row.open, row.high, row.low, row.close, row.volume)
            )
            return (
                int(ohlcv_complete),
                int(row.amount is not None),
                row.fetched_at or row.created_at,
                row.id,
            )
        for row in rows:
            # A provider may encode the same daily bar at midnight while
            # another uses the exchange close time.  Daily selection must use
            # the market date, otherwise a price-only Yahoo row and an
            # amount-complete AKShare row survive side by side.
            key = row.market_date if interval == "1d" else row.bar_time
            existing = latest.get(key)
            if existing is None or quality(row) > quality(existing):
                latest[key] = row
        ordered=sorted(latest.items(), key=lambda x: x[1].market_date or x[0]); idx=pd.DatetimeIndex([r.market_date if interval=="1d" else k for k,r in ordered]); return pd.DataFrame([{"Open":r.open,"High":r.high,"Low":r.low,"Close":r.close,"Adj Close":r.adjusted_close,"Volume":r.volume,"Amount":r.amount,"Dividends":r.dividends,"Stock Splits":r.stock_splits} for _,r in ordered],index=idx)
    def get_latest_daily_bars(self,symbol,start_date,end_date,include_unfinished=False): return self.get_latest_bars(symbol,"1d",start_date,end_date,include_unfinished)
    def get_latest_intraday_bars(self,symbol,start_time,end_time): return self.get_latest_bars(symbol,"5m",start_time,end_time,True)
    def get_bar_coverage(self,symbol,interval,start_time=None,end_time=None):
        frame=self.get_latest_bars(symbol,interval,start_time,end_time)
        start=pd.Timestamp(start_time) if start_time is not None else None; end=pd.Timestamp(end_time) if end_time is not None else None
        return {"symbol":symbol,"interval":interval,"row_count":len(frame),"first_bar":str(frame.index[0]) if len(frame) else None,"latest_bar":str(frame.index[-1]) if len(frame) else None,"requested_start":str(start_time),"requested_end":str(end_time),"has_data":not frame.empty,"covers_start":not frame.empty and (start is None or frame.index[0]<=start),"covers_end":not frame.empty and (end is None or frame.index[-1]>=end)}
