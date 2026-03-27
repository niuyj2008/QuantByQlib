"""
六维技术评分系统 (Technical Scorer)

参考 daily_stock_analysis 的加权评分体系，基于原始 OHLCV 数据计算可解释的技术评分。
与 Alpha158 特征互补：Alpha158 擅长机器学习特征，本模块擅长人类可读的技术信号。

评分维度与权重：
  1. MA 趋势     30%  均线多头排列程度
  2. 背离率      20%  价格偏离 MA20（超过 5% 触发追涨警告）
  3. 量能模式    15%  量能与价格方向的配合度
  4. MACD        15%  金叉/死叉/柱量方向
  5. RSI 动量    10%  超买超卖判断（RSI6/12/24）
  6. 布林带位置  10%  价格相对布林带上下轨的位置

返回值：TechnicalScore 数据类
  - 各维度 0-100 分
  - 综合百分制评分
  - 信号标签（强买/买/观望/卖/强卖）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class TechnicalScore:
    """六维技术评分结果"""
    ticker:           str

    # 各维度分数（0-100）
    ma_trend_score:   Optional[float] = None   # MA 趋势
    deviation_score:  Optional[float] = None   # 背离率
    volume_score:     Optional[float] = None   # 量能模式
    macd_score:       Optional[float] = None   # MACD
    rsi_score:        Optional[float] = None   # RSI
    bband_score:      Optional[float] = None   # 布林带位置

    # 综合评分
    total_score:      Optional[float] = None   # 0-100
    signal:           Optional[str]   = None   # 强买/买/观望/卖/强卖
    signal_type:      Optional[str]   = None   # bullish/neutral/bearish

    # 关键数值（供 UI 展示）
    current_price:    Optional[float] = None
    ma5:              Optional[float] = None
    ma10:             Optional[float] = None
    ma20:             Optional[float] = None
    ma60:             Optional[float] = None
    deviation_pct:    Optional[float] = None   # 相对 MA20 的背离率（%）
    chase_warning:    bool            = False   # True = 追涨风险（背离率 > 5%）
    macd_line:        Optional[float] = None
    macd_signal:      Optional[float] = None
    macd_hist:        Optional[float] = None
    macd_cross:       Optional[str]   = None   # "金叉" / "死叉" / "中性"
    rsi6:             Optional[float] = None
    rsi12:            Optional[float] = None
    rsi24:            Optional[float] = None
    bband_upper:      Optional[float] = None
    bband_lower:      Optional[float] = None
    bband_pct:        Optional[float] = None   # 布林带 %B（0=下轨,1=上轨）

    available:        bool            = False

    def to_dimension_list(self) -> list[dict]:
        """返回各维度评分列表，供 UI 渲染雷达图/条形图"""
        dims = [
            ("MA 趋势",   self.ma_trend_score,  "30%"),
            ("背离率",    self.deviation_score,  "20%"),
            ("量能模式",  self.volume_score,     "15%"),
            ("MACD",      self.macd_score,       "15%"),
            ("RSI 动量",  self.rsi_score,        "10%"),
            ("布林带",    self.bband_score,      "10%"),
        ]
        return [
            {"name": name, "score": score, "weight": w}
            for name, score, w in dims
            if score is not None
        ]


# ── 评分器 ────────────────────────────────────────────────────

class TechnicalScorer:
    """
    基于 OHLCV DataFrame 计算六维技术评分。
    输入数据由 market_data_client.get_ohlcv_period() 或 ChartData.ohlcv 提供。
    """

    # 权重（总和 = 1.0）
    WEIGHTS = {
        "ma_trend":  0.30,
        "deviation": 0.20,
        "volume":    0.15,
        "macd":      0.15,
        "rsi":       0.10,
        "bband":     0.10,
    }

    def score(self, ticker: str, ohlcv: pd.DataFrame) -> TechnicalScore:
        """
        计算六维技术评分。

        参数:
            ticker: 股票代码（仅用于日志）
            ohlcv:  标准化 DataFrame，列含 open/high/low/close/volume，DatetimeIndex
        """
        result = TechnicalScore(ticker=ticker)

        if ohlcv is None or ohlcv.empty or len(ohlcv) < 5:
            logger.debug(f"[TechnicalScorer] {ticker} 数据不足，跳过评分")
            return result

        if "close" not in ohlcv.columns:
            logger.debug(f"[TechnicalScorer] {ticker} 缺少 close 列")
            return result

        close  = ohlcv["close"].dropna()
        volume = ohlcv["volume"].dropna() if "volume" in ohlcv.columns else None

        if len(close) < 5:
            return result

        current = float(close.iloc[-1])
        result.current_price = current

        # 计算各维度
        result.ma5  = _ma(close, 5)
        result.ma10 = _ma(close, 10)
        result.ma20 = _ma(close, 20)
        result.ma60 = _ma(close, 60)

        result.ma_trend_score  = self._score_ma_trend(current, result.ma5, result.ma10, result.ma20, result.ma60)
        result.deviation_score, result.deviation_pct, result.chase_warning = self._score_deviation(current, result.ma20)
        result.volume_score    = self._score_volume(close, volume)
        result.macd_score, result.macd_line, result.macd_signal, result.macd_hist, result.macd_cross = self._score_macd(close)
        result.rsi_score, result.rsi6, result.rsi12, result.rsi24 = self._score_rsi(close)
        result.bband_score, result.bband_upper, result.bband_lower, result.bband_pct = self._score_bband(close, result.ma20)

        # 加权综合评分
        dim_scores = {
            "ma_trend":  result.ma_trend_score,
            "deviation": result.deviation_score,
            "volume":    result.volume_score,
            "macd":      result.macd_score,
            "rsi":       result.rsi_score,
            "bband":     result.bband_score,
        }
        available = {k: v for k, v in dim_scores.items() if v is not None}
        if not available:
            return result

        total_weight = sum(self.WEIGHTS[k] for k in available)
        if total_weight <= 0:
            return result

        weighted = sum(available[k] * self.WEIGHTS[k] for k in available)
        total = round(weighted / total_weight, 1)
        result.total_score = total

        # 信号标签
        if total >= 75:
            result.signal, result.signal_type = "强买", "bullish"
        elif total >= 60:
            result.signal, result.signal_type = "买入", "bullish"
        elif total >= 45:
            result.signal, result.signal_type = "观望", "neutral"
        elif total >= 30:
            result.signal, result.signal_type = "卖出", "bearish"
        else:
            result.signal, result.signal_type = "强卖", "bearish"

        result.available = True
        logger.debug(f"[TechnicalScorer] {ticker} 技术评分={total}（{result.signal}）"
                     f" MA={result.ma_trend_score} 背离={result.deviation_score}"
                     f" 量能={result.volume_score} MACD={result.macd_score}"
                     f" RSI={result.rsi_score} 布林={result.bband_score}")
        return result

    # ── 各维度评分 ─────────────────────────────────────────────

    def _score_ma_trend(
        self,
        price: float,
        ma5: Optional[float],
        ma10: Optional[float],
        ma20: Optional[float],
        ma60: Optional[float],
    ) -> Optional[float]:
        """
        MA 趋势评分（0-100）
        多头排列（MA5 > MA10 > MA20 > MA60，且价格 > MA5）最高分
        逐步降级扣分
        """
        available_mas = [(5, ma5), (10, ma10), (20, ma20), (60, ma60)]
        available_mas = [(n, v) for n, v in available_mas if v is not None]
        if not available_mas:
            return None

        score = 50.0  # 基础分

        # 价格与各均线的关系
        above_count = sum(1 for _, v in available_mas if price > v)
        above_ratio = above_count / len(available_mas)
        score += (above_ratio - 0.5) * 40  # -20 ~ +20

        # 均线多头/空头排列
        if len(available_mas) >= 2:
            vals = [v for _, v in available_mas]
            pairs = [(vals[i], vals[i + 1]) for i in range(len(vals) - 1)]
            bull_pairs = sum(1 for a, b in pairs if a > b)   # 短均线 > 长均线
            bull_ratio = bull_pairs / len(pairs)
            score += (bull_ratio - 0.5) * 30  # -15 ~ +15

        # 价格 > MA5 是最直接的强势信号
        if ma5 is not None:
            if price > ma5 * 1.01:
                score += 8
            elif price < ma5 * 0.99:
                score -= 8

        return float(max(0.0, min(100.0, score)))

    def _score_deviation(
        self,
        price: float,
        ma20: Optional[float],
    ) -> tuple[Optional[float], Optional[float], bool]:
        """
        背离率评分（0-100），返回 (score, deviation_pct, chase_warning)
        偏离 0-3%：中性
        偏离 3-5%（上方）：轻微追涨，扣分
        偏离 > 5%（上方）：高追涨风险，大幅扣分 + 触发警告
        偏离 < -5%（下方）：超跌区域，相对加分
        """
        if ma20 is None or ma20 <= 0:
            return None, None, False

        dev_pct = (price / ma20 - 1) * 100  # 正 = 价格高于MA20

        chase_warning = dev_pct > 5.0

        if dev_pct > 10:
            score = 20.0   # 严重高估/追涨
        elif dev_pct > 5:
            score = 35.0   # 追涨警戒
        elif dev_pct > 3:
            score = 50.0   # 轻微偏高
        elif dev_pct > -3:
            score = 65.0   # 健康区间（靠近均线）
        elif dev_pct > -5:
            score = 75.0   # 轻微回调，买入机会
        elif dev_pct > -10:
            score = 80.0   # 超跌，价值区
        else:
            score = 55.0   # 大幅超跌，趋势可能破坏

        return float(score), round(dev_pct, 2), chase_warning

    def _score_volume(
        self,
        close: pd.Series,
        volume: Optional[pd.Series],
    ) -> Optional[float]:
        """
        量能模式评分（0-100）
        上涨放量 + 下跌缩量 = 最佳
        上涨缩量 = 中性
        下跌放量 = 警示
        """
        if volume is None or len(volume) < 6:
            return None

        try:
            # 5 日平均量
            avg5 = float(volume.iloc[-6:-1].mean())
            latest_vol = float(volume.iloc[-1])
            price_change = float(close.iloc[-1]) - float(close.iloc[-2]) if len(close) >= 2 else 0.0

            if avg5 <= 0:
                return None

            vol_ratio = latest_vol / avg5  # > 1 = 放量

            # 量价配合度
            if price_change > 0 and vol_ratio > 1.2:
                score = 80.0   # 上涨放量（最佳）
            elif price_change > 0 and vol_ratio < 0.8:
                score = 55.0   # 上涨缩量（需验证）
            elif price_change > 0:
                score = 65.0   # 上涨平量
            elif price_change < 0 and vol_ratio < 0.8:
                score = 70.0   # 下跌缩量（洗盘）
            elif price_change < 0 and vol_ratio > 1.5:
                score = 25.0   # 下跌放量（出货）
            elif price_change < 0:
                score = 45.0   # 下跌平量
            else:
                score = 50.0   # 横盘

            # 额外：近 5 日量能趋势（量能是否逐步放大）
            if len(volume) >= 10:
                vol_5d_avg = float(volume.iloc[-5:].mean())
                vol_10d_avg = float(volume.iloc[-10:-5].mean())
                if vol_10d_avg > 0:
                    vol_trend = vol_5d_avg / vol_10d_avg
                    if vol_trend > 1.2:
                        score = min(score + 5, 100)
                    elif vol_trend < 0.8:
                        score = max(score - 5, 0)

            return float(score)
        except Exception as e:
            logger.debug(f"量能评分失败：{e}")
            return None

    def _score_macd(
        self,
        close: pd.Series,
    ) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[str]]:
        """
        MACD 评分（0-100），返回 (score, macd_line, signal_line, hist, cross_type)
        参数：12/26/9（标准参数）
        """
        if len(close) < 26:
            return None, None, None, None, None

        try:
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd  = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            hist  = macd - signal

            macd_val   = float(macd.iloc[-1])
            signal_val = float(signal.iloc[-1])
            hist_val   = float(hist.iloc[-1])
            hist_prev  = float(hist.iloc[-2]) if len(hist) >= 2 else hist_val

            # 金叉/死叉判断（近 3 根柱子内有交叉）
            cross = "中性"
            if len(hist) >= 3:
                h_vals = [float(hist.iloc[i]) for i in range(-3, 0)]
                if h_vals[-2] < 0 and h_vals[-1] > 0:
                    cross = "金叉"
                elif h_vals[-2] > 0 and h_vals[-1] < 0:
                    cross = "死叉"

            score = 50.0

            # MACD 线方向（正值看多）
            if macd_val > 0:
                score += 15
            else:
                score -= 15

            # MACD > 信号线（多头）
            if macd_val > signal_val:
                score += 10
            else:
                score -= 10

            # 柱量方向
            if hist_val > 0:
                score += 8
                if hist_val > hist_prev:    # 柱量增大
                    score += 7
            else:
                score -= 8
                if hist_val < hist_prev:    # 柱量扩大（下行）
                    score -= 7

            # 金叉/死叉奖惩
            if cross == "金叉":
                score += 10
                if macd_val > 0:            # 零轴上方金叉最强
                    score += 5
            elif cross == "死叉":
                score -= 10

            return (
                float(max(0.0, min(100.0, score))),
                round(macd_val, 4),
                round(signal_val, 4),
                round(hist_val, 4),
                cross,
            )
        except Exception as e:
            logger.debug(f"MACD 评分失败：{e}")
            return None, None, None, None, None

    def _score_rsi(
        self,
        close: pd.Series,
    ) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """
        RSI 评分（0-100），返回 (score, rsi6, rsi12, rsi24)
        超卖区（<30）看多；超买区（>70）看空；40-60 中性
        """
        def calc_rsi(s: pd.Series, period: int) -> Optional[float]:
            if len(s) < period + 1:
                return None
            delta = s.diff()
            gain  = delta.clip(lower=0).rolling(period).mean()
            loss  = (-delta.clip(upper=0)).rolling(period).mean()
            rs    = gain / (loss + 1e-9)
            rsi   = 100 - (100 / (1 + rs))
            val   = rsi.iloc[-1]
            return round(float(val), 1) if not np.isnan(val) else None

        rsi6  = calc_rsi(close, 6)
        rsi12 = calc_rsi(close, 12)
        rsi24 = calc_rsi(close, 24)

        available = [v for v in [rsi6, rsi12, rsi24] if v is not None]
        if not available:
            return None, rsi6, rsi12, rsi24

        avg_rsi = sum(available) / len(available)

        # RSI 转换为评分（超卖=高分，超买=低分）
        # 30 以下：买入区；30-50：偏空；50-70：偏多；70 以上：卖出区
        if avg_rsi < 20:
            score = 90.0   # 深度超卖
        elif avg_rsi < 30:
            score = 80.0   # 超卖
        elif avg_rsi < 40:
            score = 65.0   # 弱势偏低
        elif avg_rsi < 50:
            score = 55.0   # 中性偏空
        elif avg_rsi < 60:
            score = 55.0   # 中性偏多
        elif avg_rsi < 70:
            score = 60.0   # 偏强
        elif avg_rsi < 80:
            score = 35.0   # 超买警告
        else:
            score = 20.0   # 深度超买

        # 短周期 RSI6 方向修正（动量）
        if rsi6 is not None and rsi12 is not None:
            if rsi6 > rsi12:
                score = min(score + 5, 100)   # RSI6 上穿 RSI12，动量向上
            else:
                score = max(score - 5, 0)

        return float(score), rsi6, rsi12, rsi24

    def _score_bband(
        self,
        close: pd.Series,
        ma20: Optional[float],
    ) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """
        布林带评分（0-100），返回 (score, upper, lower, pct_b)
        %B = (price - lower) / (upper - lower)
        0 = 触下轨（超跌买入机会）；1 = 触上轨（超买卖出机会）
        """
        if len(close) < 20 or ma20 is None:
            return None, None, None, None

        try:
            std20 = float(close.rolling(20).std().iloc[-1])
            upper = ma20 + 2 * std20
            lower = ma20 - 2 * std20
            price = float(close.iloc[-1])

            band_width = upper - lower
            if band_width <= 0:
                return None, upper, lower, None

            pct_b = (price - lower) / band_width  # 0 = 下轨，1 = 上轨

            # 买点：价格接近下轨；卖点：接近上轨
            if pct_b < 0.1:
                score = 85.0    # 触下轨，超跌反弹机会
            elif pct_b < 0.25:
                score = 72.0    # 下轨附近
            elif pct_b < 0.4:
                score = 62.0    # 偏低
            elif pct_b < 0.6:
                score = 55.0    # 中间区域
            elif pct_b < 0.75:
                score = 48.0    # 偏高
            elif pct_b < 0.9:
                score = 35.0    # 上轨附近，注意
            else:
                score = 20.0    # 触上轨，超买

            return float(score), round(upper, 2), round(lower, 2), round(pct_b, 3)
        except Exception as e:
            logger.debug(f"布林带评分失败：{e}")
            return None, None, None, None


# ── 工具函数 ──────────────────────────────────────────────────

def _ma(series: pd.Series, period: int) -> Optional[float]:
    """计算简单移动平均，数据不足时返回 None"""
    if len(series) < period:
        return None
    val = series.rolling(period).mean().iloc[-1]
    return round(float(val), 2) if not np.isnan(val) else None
