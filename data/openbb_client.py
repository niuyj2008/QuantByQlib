"""
OpenBB Platform 统一数据接入层
所有市场/基本面/新闻数据均通过此模块获取，禁止在其他模块直接调用 openbb

失败策略：所有方法失败时返回 None（不抛异常），调用方检查 None 后显示"暂无数据"
"""
from __future__ import annotations

import os
from typing import Optional
from loguru import logger


def _get_obb():
    """懒加载 OpenBB 实例，确保 API Key 已从环境变量中读取"""
    try:
        from openbb import obb
        _configure_providers(obb)
        return obb
    except ImportError:
        logger.warning("OpenBB 未安装，请运行：pip3 install openbb")
        return None
    except Exception as e:
        logger.warning(f"OpenBB 初始化失败：{e}")
        return None


def _configure_providers(obb) -> None:
    """将 .env 中的 API Key 注入 OpenBB"""
    try:
        fmp_key = os.environ.get("FMP_API_KEY", "")
        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        av_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")

        creds = obb.user.credentials
        if fmp_key:
            try:
                creds.fmp_api_key = fmp_key
            except Exception:
                pass
        if finnhub_key:
            try:
                creds.finnhub_api_key = finnhub_key
            except Exception:
                pass
        if av_key:
            try:
                creds.alpha_vantage_api_key = av_key
            except Exception:
                pass
    except Exception:
        pass  # 配置失败不影响启动


# ── 行情数据 ──────────────────────────────────────────────────

def get_price_history(
    ticker: str,
    start_date: str,
    end_date: str,
    provider_priority: list[str] | None = None,
) -> Optional[object]:
    """
    获取 OHLCV 历史行情
    provider 优先级：alpha_vantage → yfinance
    返回 OpenBB OBBject（.to_dataframe() 可得 DataFrame），失败返回 None
    """
    obb = _get_obb()
    if obb is None:
        return None

    providers = provider_priority or ["alpha_vantage", "yfinance"]
    for provider in providers:
        try:
            result = obb.equity.price.historical(
                symbol=ticker,
                start_date=start_date,
                end_date=end_date,
                provider=provider,
            )
            if result and result.results:
                logger.debug(f"行情数据 {ticker} 来自 {provider}")
                return result
        except Exception as e:
            logger.debug(f"行情 provider {provider} 失败：{e}")
            continue

    logger.warning(f"所有 provider 均无法获取 {ticker} 行情数据")
    return None


def get_latest_quote(ticker: str) -> Optional[dict]:
    """
    获取最新报价（当前价/涨跌幅）
    返回 dict：{price, change, change_pct, volume} 或 None
    """
    obb = _get_obb()
    if obb is None:
        return None

    for provider in ["yfinance", "fmp"]:
        try:
            result = obb.equity.price.quote(symbol=ticker, provider=provider)
            if result and result.results:
                row = result.to_dataframe().iloc[0]
                return {
                    "price":      _safe_float(row, ["last_price", "price", "close"]),
                    "change":     _safe_float(row, ["change", "price_change"]),
                    "change_pct": _safe_float(row, ["change_percent", "price_change_percent"]),
                    "volume":     _safe_float(row, ["volume"]),
                    "provider":   provider,
                }
        except Exception as e:
            logger.debug(f"报价 provider {provider} 失败：{e}")
            continue

    return None


def get_batch_quotes(tickers: list[str]) -> dict[str, Optional[dict]]:
    """
    批量获取多只股票的最新报价
    返回 {ticker: quote_dict or None}
    """
    results = {}
    for ticker in tickers:
        results[ticker] = get_latest_quote(ticker)
    return results


# ── 基本面数据 ────────────────────────────────────────────────

def get_fundamental_metrics(ticker: str) -> Optional[dict]:
    """
    获取基本面指标（PE/PB/市值/ROE 等）via FMP
    返回 dict 或 None
    """
    obb = _get_obb()
    if obb is None:
        return None

    try:
        result = obb.equity.fundamental.metrics(
            symbol=ticker,
            provider="fmp",
            period="annual",
            limit=1,
        )
        if result and result.results:
            row = result.to_dataframe().iloc[0]
            return {
                "pe_ratio":        _safe_float(row, ["pe_ratio", "pe"]),
                "pb_ratio":        _safe_float(row, ["pb_ratio", "pb"]),
                "ps_ratio":        _safe_float(row, ["ps_ratio", "ps"]),
                "roe":             _safe_float(row, ["return_on_equity", "roe"]),
                "roa":             _safe_float(row, ["return_on_assets", "roa"]),
                "debt_to_equity":  _safe_float(row, ["debt_to_equity"]),
                "current_ratio":   _safe_float(row, ["current_ratio"]),
                "revenue_growth":  _safe_float(row, ["revenue_growth"]),
                "eps_growth":      _safe_float(row, ["eps_growth"]),
                "gross_margin":    _safe_float(row, ["gross_profit_margin", "gross_margin"]),
                "operating_margin":_safe_float(row, ["operating_profit_margin", "operating_margin"]),
                "net_margin":      _safe_float(row, ["net_profit_margin", "net_margin"]),
            }
    except Exception as e:
        logger.debug(f"基本面指标 {ticker} 失败：{e}")

    return None


def get_company_profile(ticker: str) -> Optional[dict]:
    """
    获取公司概况（名称/行业/市值/描述/分析师目标价）via FMP
    返回 dict 或 None
    """
    obb = _get_obb()
    if obb is None:
        return None

    profile = None
    try:
        result = obb.equity.profile(symbol=ticker, provider="fmp")
        if result and result.results:
            row = result.to_dataframe().iloc[0]
            profile = {
                "name":        _safe_str(row, ["long_name", "name", "company_name"]),
                "sector":      _safe_str(row, ["sector"]),
                "industry":    _safe_str(row, ["industry"]),
                "market_cap":  _safe_float(row, ["market_cap"]),
                "description": _safe_str(row, ["description", "long_business_summary"]),
                "employees":   _safe_float(row, ["full_time_employees"]),
                "country":     _safe_str(row, ["country"]),
                "website":     _safe_str(row, ["website"]),
                "exchange":    _safe_str(row, ["exchange"]),
            }
    except Exception as e:
        logger.debug(f"公司概况 {ticker} 失败：{e}")

    # 追加分析师目标价
    try:
        pt_result = obb.equity.estimates.price_target(symbol=ticker, provider="fmp")
        if pt_result and pt_result.results:
            pt_row = pt_result.to_dataframe().iloc[0]
            if profile is None:
                profile = {}
            profile["analyst_target"] = _safe_float(pt_row, ["price_target", "target_price"])
            profile["analyst_rating"] = _safe_str(pt_row, ["rating", "consensus"])
    except Exception as e:
        logger.debug(f"分析师目标价 {ticker} 失败：{e}")

    return profile


def get_earnings_history(ticker: str, limit: int = 8) -> Optional[list[dict]]:
    """
    获取历史 EPS 实际/预期对比 via FMP
    返回 list[dict] 或 None
    """
    obb = _get_obb()
    if obb is None:
        return None

    try:
        result = obb.equity.fundamental.earnings(
            symbol=ticker,
            provider="fmp",
            limit=limit,
        )
        if result and result.results:
            df = result.to_dataframe()
            records = []
            for _, row in df.iterrows():
                records.append({
                    "date":          str(row.get("date", "--")),
                    "eps_actual":    _safe_float(row, ["eps_actual", "actual_eps"]),
                    "eps_estimated": _safe_float(row, ["eps_estimated", "estimated_eps"]),
                    "revenue_actual":    _safe_float(row, ["revenue_actual"]),
                    "revenue_estimated": _safe_float(row, ["revenue_estimated"]),
                })
            return records
    except Exception as e:
        logger.debug(f"EPS 历史 {ticker} 失败：{e}")

    return None


# ── 新闻与情绪 ────────────────────────────────────────────────

def get_news(ticker: str, limit: int = 20) -> list[dict]:
    """
    获取个股新闻 via Finnhub
    返回 list[dict]，失败返回空列表（不返回 None）
    每条包含：headline / summary / url / datetime / sentiment_source
    """
    obb = _get_obb()
    if obb is None:
        return []

    for provider in ["fmp", "tiingo", "benzinga"]:
        try:
            result = obb.news.company(
                symbol=ticker,
                provider=provider,
                limit=limit,
            )
            if result and result.results:
                df = result.to_dataframe()
                records = []
                for _, row in df.iterrows():
                    records.append({
                        "headline": _safe_str(row, ["headline", "title", "text"]),
                        "summary":  _safe_str(row, ["summary", "description", "body"]),
                        "url":      _safe_str(row, ["url", "link"]),
                        "datetime": str(row.get("date", row.get("published_utc", "--"))),
                        "source":   _safe_str(row, ["source", "publisher"]),
                    })
                logger.debug(f"新闻 {ticker} 来自 {provider}，共 {len(records)} 条")
                return records
        except Exception as e:
            logger.debug(f"新闻 provider {provider} 失败：{e}")
            continue

    return []


# ── 期权数据 ──────────────────────────────────────────────────

def get_options_chain(ticker: str) -> Optional[object]:
    """
    获取期权链 via CBOE（无需 API Key）
    返回 OBBject 或 None
    """
    obb = _get_obb()
    if obb is None:
        return None

    try:
        result = obb.derivatives.options.chains(symbol=ticker, provider="cboe")
        if result and result.results:
            return result
    except Exception as e:
        logger.debug(f"期权链 {ticker} 失败：{e}")

    return None


# ── 宏观数据 ──────────────────────────────────────────────────

def get_macro_indicator(series_id: str, limit: int = 60) -> Optional[object]:
    """
    获取 FRED 宏观指标（无需 API Key）
    series_id 示例：FEDFUNDS（联邦基金利率）、T10Y2Y（收益率曲线）
    返回 OBBject 或 None
    """
    obb = _get_obb()
    if obb is None:
        return None

    try:
        result = obb.economy.fred_series(symbol=series_id, limit=limit, provider="fred")
        if result and result.results:
            return result
    except Exception as e:
        logger.debug(f"宏观数据 {series_id} 失败：{e}")

    return None


# ── 连接测试 ──────────────────────────────────────────────────

def test_connection() -> dict[str, bool]:
    """
    测试各数据源连通性
    返回 {provider_name: True/False}
    """
    results = {}

    # yfinance（无需 Key，测试基础连通）
    try:
        r = get_price_history("AAPL", "2024-01-01", "2024-01-05", ["yfinance"])
        results["yfinance"] = r is not None
    except Exception:
        results["yfinance"] = False

    # FMP
    try:
        r = get_company_profile("AAPL")
        results["fmp"] = r is not None and r.get("name") is not None
    except Exception:
        results["fmp"] = False

    # 新闻（benzinga）
    try:
        news = get_news("AAPL", limit=1)
        results["benzinga"] = len(news) > 0
    except Exception:
        results["benzinga"] = False

    # Alpha Vantage
    try:
        r = get_price_history("AAPL", "2024-01-01", "2024-01-05", ["alpha_vantage"])
        results["alpha_vantage"] = r is not None
    except Exception:
        results["alpha_vantage"] = False

    logger.info(f"连接测试结果：{results}")
    return results


# ── 工具函数 ──────────────────────────────────────────────────

def _safe_float(row, field_names: list[str]) -> Optional[float]:
    """从 DataFrame 行中安全提取 float 值，尝试多个字段名"""
    import pandas as pd
    for name in field_names:
        val = row.get(name) if hasattr(row, "get") else getattr(row, name, None)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _safe_str(row, field_names: list[str]) -> Optional[str]:
    """从 DataFrame 行中安全提取 str 值，尝试多个字段名"""
    import pandas as pd
    for name in field_names:
        val = row.get(name) if hasattr(row, "get") else getattr(row, name, None)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            s = str(val).strip()
            if s and s != "nan" and s != "None":
                return s
    return None
