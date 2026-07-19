# 001309.SZ 德明利
## 单股趋势与交易倾向研究报告

> 本报告中的交易倾向是基于指定数据和规则生成的研究信号，不是自动下单指令，也不构成投资建议。

## 决策卡

- 主要周期：20～60个交易日
- 市场趋势：强烈偏弱（STRONG_BEARISH）
- 方向倾向：偏向降低风险（SELL_BIAS）
- 确认程度：仅获得技术面确认（TECHNICAL_ONLY）
- 风险等级：VERY_HIGH
- 模型自评置信度：35.00%

### 无持仓

暂不建立新多头暴露（AVOID_NEW_ENTRY）

说明：主要中期周期方向明确偏弱，且风险评级极高，暂不适宜建立新多头。

证据：
  - `market.classification.technical_score`：-0.6341（score，SUCCESS）
  - `market.classification.technical_risk_score`：0.8261（score，SUCCESS）
  - `market.moving_averages.short_structure`：STRONG_BEARISH_ALIGNMENT（enum，SUCCESS）

### 已有多头

已有多头应优先评估风险收缩（REDUCE_RISK_BIAS）

说明：中期弱势趋势叠加极端路径风险，应优先评估风险收缩而非增持。

证据：
  - `market.classification.technical_score`：-0.6341（score，SUCCESS）
  - `market.classification.technical_risk_score`：0.8261（score，SUCCESS）
  - `market.moving_averages.short_structure`：STRONG_BEARISH_ALIGNMENT（enum，SUCCESS）

### 观察名单

等待客观反转条件确认（WAIT_FOR_REVERSAL_CONFIRMATION）

说明：等待中期收益由负转正、均线斜率回升或MACD柱状图止跌等客观反转证据。

证据：
  - `market.returns.return_20d_pct`：-24.64%（percent，SUCCESS）
  - `market.moving_averages.ma20_slope_5d`：-0.53%（percent，SUCCESS）
  - `market.momentum.macd_histogram`：-43.4785（CNY，SUCCESS）

当前结论的含义：中短期市场证据明显偏弱，但基本面和新闻尚未形成交叉确认。

改变当前判断的首要条件：

1. 价格回升并站稳 20 日均线上方，均线结构由空头排列转为纠缠或金叉。
2. MACD 柱状图由负转正并持续扩大，确认下跌动能衰竭。
3. ADX 的 DI 差值收敛或转为正值，空头主导力量减弱。

## 一、核心结论

- 分析日期：2026-07-17
- 数据截止日期：2026-07-17
- 主要周期：20～60个交易日（20_TO_60_TRADING_DAYS）
- 趋势方向：STRONG_BEARISH
- 趋势强度：MODERATE
- 方向倾向：偏向降低风险（SELL_BIAS）
- 确认程度：仅获得技术面确认（TECHNICAL_ONLY）
- 风险等级：VERY_HIGH
- 模型自评置信度：35.00%
- 数据质量：PARTIAL
- 市场证据覆盖率：100.00%
- 基本面证据覆盖率：0.00%
- 新闻证据覆盖率：0.00%
- 跨领域证据覆盖率：55.00%

模型自评置信度尚未经过历史校准，不代表真实成功概率。

## 二、多周期涨跌幅

收益定义为“当前技术价格 / 向前偏移 N 个交易行的技术价格 - 1”，因此 N 日收益需要 N+1 条有效记录。

| 交易周期 | 收益 | 状态 | 所需记录数 |
|---|---:|---|---:|
| 5日 | -32.93% | SUCCESS | 6 |
| 10日 | -39.16% | SUCCESS | 11 |
| 20日 | -24.64% | SUCCESS | 21 |
| 40日 | -18.22% | SUCCESS | 41 |
| 60日 | 4.18% | SUCCESS | 61 |
| 120日 | 111.44% | SUCCESS | 121 |
| 200日 | 355.52% | SUCCESS | 201 |

## 三、MA5/MA10/MA20短期结构

- MA5 / MA10 / MA20：650.22 / 752.25 / 808.28
- 技术收盘价相对 MA5 / MA10 / MA20：-17.48% / -28.68% / -33.62%
- MA5 三日斜率：-17.52%
- MA10 五日斜率：-14.23%
- MA20 五日斜率：-0.53%
- 短期结构：STRONG_BEARISH_ALIGNMENT
- 均线纠缠阈值：最大均线跨度不超过 2.00%（第一版工程规则）

## 四、中期均线与趋势强度

- MA50 / MA200：717.10 / 388.51
- MA50 十日斜率 / MA200 二十日斜率：6.77% / 22.40%
- ADX14：34.53，强度分类：ESTABLISHED_TREND
- +DI14 / -DI14 / DI差：18.11 / 32.46 / -14.35

ADX 只表示趋势强度，不表示趋势方向；方向由收益路径、均线结构与 +DI/-DI 等共同确认。

## 五、动量、量价和路径质量

- RSI14：33.33
- MACD Histogram / 五日变化：-43.4785 / -32.3459
- 最新成交量 / 前20行平均量 / 20日量比：2107600 / 15232887 / 0.1384
- 20日 / 60日上涨日比例：50.00% / 55.00%
- 20日 / 60日年化历史波动率代理：114.59% / 91.13%
- 20日 / 60日 / 120日真实最大回撤：-44.69% / -44.69% / -44.69%
- 路径质量：HIGHLY_UNSTABLE

历史波动率仅是年化代理，不是未来波动率预测；最大回撤按窗口完整路径和逐日累计高点计算。

## 六、确定性趋势分类

- 收益趋势分：-0.5500
- 短期均线结构分：-1.0000
- 中期均线结构分：-0.4910
- 动量分：-0.8750
- 量价确认分：0.0000
- 技术总分：-0.6341
- 技术风险分：0.8261
- 短期 / 中期 / 长期：STRONG_BEARISH / BEARISH / STRONG_BULLISH
- 综合确定性趋势：STRONG_BEARISH

技术总分以多周期收益为主要部分；方向分与风险分分离。分类阈值属于工程规则，尚未经过历史回测校准。

## 七、Trader判断及证据引用

- Trader 方向倾向：偏向降低风险（SELL_BIAS）
- Trader 确认程度：仅获得技术面确认（TECHNICAL_ONLY）
- Trader 模型自评置信度：40.00%

- 中期收益在 20 日和 40 日周期均为明显负值，60 日收益仅微弱为正，下行惯性主导主要周期。
  - 证据引用：
    - `market.returns.return_20d_pct`：-24.64%（percent，SUCCESS）
    - `market.returns.return_40d_pct`：-18.22%（percent，SUCCESS）
    - `market.returns.return_60d_pct`：4.18%（percent，SUCCESS）
- 短期均线结构呈强烈空头排列，价格大幅低于 20 日均线，中期均线斜率趋平或下行，确认中期弱势。
  - 证据引用：
    - `market.moving_averages.short_structure`：STRONG_BEARISH_ALIGNMENT（enum，SUCCESS）
    - `market.moving_averages.ma20`：808.2825（CNY，SUCCESS）
    - `market.moving_averages.close_vs_ma20_pct`：-33.62%（percent，SUCCESS）
    - `market.moving_averages.ma20_slope_5d`：-0.53%（percent，SUCCESS）
- MACD 柱状图为负且大幅下降，表明下跌动能加强，方向性指向卖出。
  - 证据引用：
    - `market.momentum.macd_histogram`：-43.4785（CNY，SUCCESS）
    - `market.momentum.macd_histogram_change_5d`：-32.3459（CNY，SUCCESS）
- ADX 显示趋势已确立且 DI 差值为负，空方主导。
  - 证据引用：
    - `market.trend_strength.adx14`：34.5312（index，SUCCESS）
    - `market.trend_strength.minus_di14`：32.4567（index，SUCCESS）
    - `market.trend_strength.di_spread`：-14.3493（index，SUCCESS）

## 八、主要正向证据

- 长期收益极强，120 日和 200 日回报大幅为正，价格远高于 200 日均线，长期趋势并未破坏。
  - 证据引用：
    - `market.returns.return_120d_pct`：111.44%（percent，SUCCESS）
    - `market.returns.return_200d_pct`：355.52%（percent，SUCCESS）
    - `market.moving_averages.ma200`：388.5086（CNY，SUCCESS）
    - `market.moving_averages.close_vs_ma200_pct`：38.10%（percent，SUCCESS）
- 200 日均线仍保持明显上行斜率，长期结构暂未转向。
  - 证据引用：
    - `market.moving_averages.ma200_slope_20d`：22.40%（percent，SUCCESS）

## 九、主要负向证据

- 5 日和 10 日短期回报深度负值，价格大幅低于 5 日均线和 10 日均线，抛压沉重。
  - 证据引用：
    - `market.returns.return_5d_pct`：-32.93%（percent，SUCCESS）
    - `market.returns.return_10d_pct`：-39.16%（percent，SUCCESS）
    - `market.moving_averages.close_vs_ma5_pct`：-17.48%（percent，SUCCESS）
    - `market.moving_averages.close_vs_ma10_pct`：-28.68%（percent，SUCCESS）
- 近期成交量极度萎缩，显示市场参与度不足，下跌缺乏承接。
  - 证据引用：
    - `market.volume.volume_ratio_5d`：0.2243（ratio，SUCCESS）
    - `market.volume.volume_ratio_20d`：0.1384（ratio，SUCCESS）
- 20 日和 60 日最大回撤达极端水平，价格紧贴近期低点，路径风险极高。
  - 证据引用：
    - `market.path_risk.max_drawdown_20d_pct`：-44.69%（percent，SUCCESS）
    - `market.path_risk.max_drawdown_60d_pct`：-44.69%（percent，SUCCESS）
    - `market.path_risk.distance_from_20d_low_pct`：0.00%（percent，SUCCESS）

## 十、风险复核

- 复核状态：APPROVED_WITH_WARNINGS
- 风险等级：VERY_HIGH
- 风险复核后方向：偏向降低风险（SELL_BIAS）
- 风险复核后确认程度：仅获得技术面确认（TECHNICAL_ONLY）
- 调整后置信度：35.00%
- 证据引用审计：PASSED

调整理由：

- 长期趋势与中期趋势存在显著方向冲突，降低决策可靠性，因此小幅下调置信度。
  - 证据引用：
    - `market.returns.return_120d_pct`：111.44%（percent，SUCCESS）
    - `market.moving_averages.short_structure`：STRONG_BEARISH_ALIGNMENT（enum，SUCCESS）
- 基本面与新闻数据完全缺失，无法评估非技术因素，进一步限制决策确定性。
  - 证据引用：
    - `fundamentals.status`：FUNDAMENTALS_UNAVAILABLE（enum，SUCCESS）
    - `news.status`：SUCCESS_NO_DATA（enum，SUCCESS）
- 成交量极度萎缩，可能反映下跌趋势的持续性存疑，略微削弱信号强度。
  - 证据引用：
    - `market.volume.volume_ratio_5d`：0.2243（ratio，SUCCESS）
    - `market.volume.volume_ratio_20d`：0.1384（ratio，SUCCESS）

风险警告：

- 波动率处于极端高位，价格路径高度不稳定，任何方向均可能出现大幅波动。
  - 证据引用：
    - `market.path_risk.volatility_20d_pct`：114.59%（percent，SUCCESS）
    - `market.path_risk.volatility_60d_pct`：91.13%（percent，SUCCESS）
- 中期与长期趋势严重冲突，可能引发剧烈双向波动和假突破信号。
  - 证据引用：
    - `market.returns.return_20d_pct`：-24.64%（percent，SUCCESS）
    - `market.returns.return_120d_pct`：111.44%（percent，SUCCESS）
    - `market.moving_averages.short_structure`：STRONG_BEARISH_ALIGNMENT（enum，SUCCESS）
- 基本面与新闻信息完全缺失，无法排除未在价格中反映的重大事件或估值风险。
  - 证据引用：
    - `fundamentals.status`：FUNDAMENTALS_UNAVAILABLE（enum，SUCCESS）
    - `news.status`：SUCCESS_NO_DATA（enum，SUCCESS）
    - `data_quality.cross_domain_evidence_coverage`：0.5500（ratio，SUCCESS）

持仓情景：

- 无持仓：暂不建立新多头暴露（AVOID_NEW_ENTRY）
- 已有多头：已有多头应优先评估风险收缩（REDUCE_RISK_BIAS）
- 观察名单：等待客观反转条件确认（WAIT_FOR_REVERSAL_CONFIRMATION）

## 十一、判断失效条件

- 价格回升并站稳 20 日均线上方，均线结构由空头排列转为纠缠或金叉。
  - 证据引用：
    - `market.moving_averages.close_vs_ma20_pct`：-33.62%（percent，SUCCESS）
    - `market.moving_averages.short_structure`：STRONG_BEARISH_ALIGNMENT（enum，SUCCESS）
- MACD 柱状图由负转正并持续扩大，确认下跌动能衰竭。
  - 证据引用：
    - `market.momentum.macd_histogram`：-43.4785（CNY，SUCCESS）
- ADX 的 DI 差值收敛或转为正值，空头主导力量减弱。
  - 证据引用：
    - `market.trend_strength.di_spread`：-14.3493（index，SUCCESS）
- 20 日或 40 日收益转为正且与短期均线斜率同步向上。
  - 证据引用：
    - `market.returns.return_20d_pct`：-24.64%（percent，SUCCESS）
    - `market.moving_averages.ma20_slope_5d`：-0.53%（percent，SUCCESS）

## 十二、数据质量与价格口径

- 展示价格口径：raw；最新原始收盘价：536.54
- 技术计算价格口径：adjusted；最新复权收盘价：536.54
- 复权状态：ADJUSTED
- 复权收盘价覆盖率：100.00%
- 行情来源：database；外部行情 Provider 调用次数：0
- 证据引用数量：76；审计违规数量：0

技术 OHLC 使用同一行的 `adjusted_close / raw_close` 因子统一转换，避免复权收盘价与未复权高低价混用。

## 十三、数据限制与免责声明

- 基本面状态：FUNDAMENTALS_UNAVAILABLE；新闻状态：SUCCESS_NO_DATA；缺失数据没有被当成中性证据。
- 报告只使用截至 2026-07-17 的数据库最终日线，不提供价格预测、仓位建议或交易执行。
- 工程规则与模型自评置信度均未经过历史回测校准。
- 本报告是研究信号，不构成投资建议；投资决策及损失由使用者自行承担。
