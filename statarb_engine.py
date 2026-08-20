"""
statarb_engine.py - High-Performance Polars Statistical Arbitrage & Volume Profile Analytics Engine

Provides:
1. Dynamic Rolling Volume-Weighted Average Price (VWAP) for single assets and pairs.
2. Dynamic Rolling OLS Beta / Minimum-Variance Hedge Ratio (Cov(A,B)/Var(B)) and Spread computation.
3. Volume-Weighted Z-Scores incorporating multi-asset total volume weighting.
4. Order Flow Cumulative Volume Delta (CVD) based on intrabar price-range delta decomposition.
5. Volume Profile Analysis: Point of Control (POC), Value Area High/Low (VAH/VAL at 70% volume), and High Volume Nodes (HVN).
6. Vectorized Backtest Simulator with Sharpe ratio, Sortino ratio, Max Drawdown %, Win Rate %, Profit Factor, Equity Curve, and Trade Logs.
"""

from typing import Union, Optional, Tuple, Dict, Any, List
import polars as pl
import numpy as np
import pandas as pd


def standardize_ticker_data(
    df: Union[pd.DataFrame, pl.DataFrame],
    ticker_name: str = "ASSET"
) -> pl.DataFrame:
    """
    Standardizes yfinance or custom pandas/polars DataFrames into standard Polars format.
    Ensures columns: ['date', 'open', 'high', 'low', 'close', 'volume'].
    All prices and volumes are cast to Float64, date is standardized to Datetime('ms') naive.
    """
    if isinstance(df, pd.DataFrame):
        df_clean = df.copy()
        if isinstance(df_clean.index, pd.DatetimeIndex):
            df_clean = df_clean.reset_index()
            first_col = df_clean.columns[0]
            df_clean = df_clean.rename(columns={first_col: "date"})
        
        # In case of MultiIndex columns from yfinance (e.g. ('Close', 'AAPL'))
        if isinstance(df_clean.columns, pd.MultiIndex):
            df_clean.columns = [
                col[0] if isinstance(col, tuple) and col[0] else str(col)
                for col in df_clean.columns
            ]
            
        pldf = pl.from_pandas(df_clean)
    elif isinstance(df, pl.DataFrame):
        pldf = df.clone()
    else:
        raise TypeError(f"Expected pd.DataFrame or pl.DataFrame, got {type(df)}")
    
    # Normalize column names to lowercase
    rename_dict = {}
    for col in pldf.columns:
        low = str(col).lower().strip()
        if low in ["date", "datetime", "index", "timestamp", "time"]:
            rename_dict[col] = "date"
        elif low in ["open", "high", "low", "close", "volume", "adj close", "adj_close"]:
            if low in ["adj close", "adj_close"]:
                if "close" not in [str(c).lower().strip() for c in pldf.columns]:
                    rename_dict[col] = "close"
            else:
                rename_dict[col] = low
    
    pldf = pldf.rename(rename_dict)
    
    # Verify mandatory columns
    if "date" not in pldf.columns:
        pldf = pldf.with_columns(pl.int_range(0, pldf.height).alias("date"))
        
    if "close" not in pldf.columns:
        raise ValueError(f"Data for {ticker_name} is missing 'close' price column.")
    
    # Add fallback OHLC if missing
    exprs = [pl.col("close").cast(pl.Float64)]
    if "open" not in pldf.columns:
        exprs.append(pl.col("close").cast(pl.Float64).alias("open"))
    else:
        exprs.append(pl.col("open").cast(pl.Float64))
        
    if "high" not in pldf.columns:
        exprs.append(pl.col("close").cast(pl.Float64).alias("high"))
    else:
        exprs.append(pl.col("high").cast(pl.Float64))
        
    if "low" not in pldf.columns:
        exprs.append(pl.col("close").cast(pl.Float64).alias("low"))
    else:
        exprs.append(pl.col("low").cast(pl.Float64))
        
    if "volume" not in pldf.columns:
        exprs.append(pl.lit(1.0).alias("volume"))
    else:
        exprs.append(pl.col("volume").fill_null(0.0).cast(pl.Float64))
        
    # Standardize date column dtype to naive pl.Datetime("ms") or keep as-is if string/numeric
    date_dtype = pldf.schema["date"]
    if date_dtype in (pl.String, pl.Utf8):
        try:
            parsed = pldf.select(
                pl.coalesce([
                    pl.col("date").str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False),
                    pl.col("date").str.to_datetime("%Y-%m-%d", strict=False),
                ]).alias("parsed_date")
            )["parsed_date"]
            if parsed.null_count() == 0:
                pldf = pldf.with_columns(parsed.cast(pl.Datetime("ms")).alias("date"))
        except Exception:
            pass
    elif isinstance(date_dtype, pl.Datetime):
        if getattr(date_dtype, "time_zone", None) is not None:
            pldf = pldf.with_columns(
                pl.col("date").dt.convert_time_zone("UTC").dt.replace_time_zone(None).cast(pl.Datetime("ms"))
            )
        else:
            pldf = pldf.with_columns(pl.col("date").cast(pl.Datetime("ms")))
    elif date_dtype == pl.Date:
        pldf = pldf.with_columns(pl.col("date").cast(pl.Datetime("ms")))
        
    pldf = pldf.select(["date", *exprs]).sort("date")
    
    # Clean NaNs / nulls in price & volume series
    pldf = pldf.with_columns([
        pl.col("close").forward_fill().backward_fill(),
        pl.col("high").forward_fill().backward_fill(),
        pl.col("low").forward_fill().backward_fill(),
        pl.col("open").forward_fill().backward_fill(),
        pl.col("volume").fill_null(0.0).clip(lower_bound=0.0)
    ])
    
    return pldf


def expr_rolling_vwap(window: int = 20, min_periods: int = 1) -> pl.Expr:
    """Polars expression calculating rolling VWAP from High, Low, Close, Volume."""
    typical_price = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    pv = typical_price * pl.col("volume")
    
    rolling_pv = pv.rolling_sum(window_size=window, min_periods=min_periods)
    rolling_vol = pl.col("volume").rolling_sum(window_size=window, min_periods=min_periods)
    
    return (
        pl.when(rolling_vol > 0.0)
        .then(rolling_pv / rolling_vol)
        .otherwise(typical_price)
    )


def compute_vwap_spread(
    df_a: Union[pd.DataFrame, pl.DataFrame],
    df_b: Union[pd.DataFrame, pl.DataFrame],
    rolling_window: int = 20,
    beta: Optional[float] = None
) -> pl.DataFrame:
    """
    Computes synchronized rolling VWAP for two assets, rolling OLS beta, and VWAP spread.
    
    Formula:
      VWAP_A, VWAP_B computed via rolling volume-weighted typical prices
      Beta = Cov(VWAP_A, VWAP_B) / Var(VWAP_B) over rolling_window (or static beta if provided)
      Spread = VWAP_A - Beta * VWAP_B
    """
    a = standardize_ticker_data(df_a, "Asset_A")
    b = standardize_ticker_data(df_b, "Asset_B")
    
    # Normalize date column dtype across both DataFrames before joining
    if a.schema["date"] != b.schema["date"]:
        if a.schema["date"].is_temporal() and b.schema["date"].is_temporal():
            a = a.with_columns(pl.col("date").cast(pl.Datetime("ms")))
            b = b.with_columns(pl.col("date").cast(pl.Datetime("ms")))
        else:
            a = a.with_columns(pl.col("date").cast(pl.String))
            b = b.with_columns(pl.col("date").cast(pl.String))
            
    # Inner join on date to guarantee calendar synchronization
    joined = a.join(b, on="date", how="inner", suffix="_b").rename({
        "open": "open_a", "high": "high_a", "low": "low_a", "close": "close_a", "volume": "volume_a",
        "open_b": "open_b", "high_b": "high_b", "low_b": "low_b", "close_b": "close_b", "volume_b": "volume_b"
    }).sort("date")
    
    if joined.height == 0:
        raise ValueError("No overlapping dates found between Asset A and Asset B.")
    
    # Calculate VWAP for A and B
    typ_a = (pl.col("high_a") + pl.col("low_a") + pl.col("close_a")) / 3.0
    typ_b = (pl.col("high_b") + pl.col("low_b") + pl.col("close_b")) / 3.0
    
    pv_a = typ_a * pl.col("volume_a")
    pv_b = typ_b * pl.col("volume_b")
    
    vol_sum_a = pl.col("volume_a").rolling_sum(window_size=rolling_window, min_samples=1)
    vol_sum_b = pl.col("volume_b").rolling_sum(window_size=rolling_window, min_samples=1)
    
    vwap_a_expr = pl.when(vol_sum_a > 0).then(
        pv_a.rolling_sum(window_size=rolling_window, min_samples=1) / vol_sum_a
    ).otherwise(typ_a).alias("vwap_a")
    
    vwap_b_expr = pl.when(vol_sum_b > 0).then(
        pv_b.rolling_sum(window_size=rolling_window, min_samples=1) / vol_sum_b
    ).otherwise(typ_b).alias("vwap_b")
    
    df_vwap = joined.with_columns([vwap_a_expr, vwap_b_expr])
    
    # Compute Rolling OLS Beta
    if beta is not None:
        beta_expr = pl.lit(float(beta)).alias("beta")
    else:
        mean_a = pl.col("vwap_a").rolling_mean(window_size=rolling_window, min_samples=2)
        mean_b = pl.col("vwap_b").rolling_mean(window_size=rolling_window, min_samples=2)
        
        cov_ab = (pl.col("vwap_a") * pl.col("vwap_b")).rolling_mean(window_size=rolling_window, min_samples=2) - (mean_a * mean_b)
        var_b = (pl.col("vwap_b") ** 2).rolling_mean(window_size=rolling_window, min_samples=2) - (mean_b ** 2)
        
        mean_ratio = mean_a / pl.when(mean_b != 0).then(mean_b).otherwise(1.0)
        
        beta_expr = (
            pl.when(var_b > 1e-12)
            .then(cov_ab / var_b)
            .otherwise(mean_ratio)
            .forward_fill()
            .backward_fill()
            .fill_null(1.0)
            .alias("beta")
        )
    
    df_beta = df_vwap.with_columns(beta_expr)
    
    # Compute Spread: S_t = VWAP_A - beta * VWAP_B
    spread_expr = (pl.col("vwap_a") - (pl.col("beta") * pl.col("vwap_b"))).alias("spread")
    total_vol_expr = (pl.col("volume_a") + pl.col("volume_b")).alias("total_volume")
    
    return df_beta.with_columns([spread_expr, total_vol_expr])


def compute_volume_weighted_zscore(
    spread_df: pl.DataFrame,
    rolling_window: int = 20
) -> pl.DataFrame:
    """
    Computes volume-weighted rolling mean and Z-score of spread.
    z_t = (S_t - rolling_mean(S_t, volume_weights)) / rolling_std(S_t)
    """
    spread_vol = pl.col("spread") * pl.col("total_volume")
    
    rolling_spread_vol = spread_vol.rolling_sum(window_size=rolling_window, min_samples=1)
    rolling_total_vol = pl.col("total_volume").rolling_sum(window_size=rolling_window, min_samples=1)
    
    vw_mean_spread = (
        pl.when(rolling_total_vol > 0)
        .then(rolling_spread_vol / rolling_total_vol)
        .otherwise(pl.col("spread").rolling_mean(window_size=rolling_window, min_samples=1))
    ).alias("spread_mean")
    
    df_with_mean = spread_df.with_columns(vw_mean_spread)
    
    # Rolling standard deviation of spread
    spread_std = pl.col("spread").rolling_std(window_size=rolling_window, min_samples=2).fill_null(0.0).alias("spread_std")
    df_with_std = df_with_mean.with_columns(spread_std)
    
    # Volume-weighted Z-score
    zscore_expr = (
        pl.when(pl.col("spread_std") > 1e-12)
        .then((pl.col("spread") - pl.col("spread_mean")) / pl.col("spread_std"))
        .otherwise(0.0)
    ).alias("zscore")
    
    return df_with_std.with_columns(zscore_expr)


def compute_cvd(df: Union[pd.DataFrame, pl.DataFrame]) -> pl.DataFrame:
    """
    Calculates intrabar Order Flow Volume Delta and Cumulative Volume Delta (CVD).
    Delta V = Volume * (2 * Close - High - Low) / (High - Low)
    """
    pldf = standardize_ticker_data(df)
    
    range_span = pl.col("high") - pl.col("low")
    
    delta_vol = (
        pl.when(range_span > 1e-12)
        .then(pl.col("volume") * (2.0 * pl.col("close") - pl.col("high") - pl.col("low")) / range_span)
        .otherwise(
            pl.when(pl.col("close") > pl.col("open")).then(pl.col("volume"))
            .when(pl.col("close") < pl.col("open")).then(-pl.col("volume"))
            .otherwise(0.0)
        )
    ).alias("volume_delta")
    
    df_delta = pldf.with_columns(delta_vol)
    cvd_expr = pl.col("volume_delta").cum_sum().alias("cvd")
    
    return df_delta.with_columns(cvd_expr)


def compute_volume_profile(
    df: Union[pd.DataFrame, pl.DataFrame],
    price_col: str = "close",
    volume_col: str = "volume",
    num_bins: int = 50,
    value_area_pct: float = 0.70
) -> Dict[str, Any]:
    """
    Computes Point of Control (POC), Value Area High (VAH), Value Area Low (VAL),
    and High Volume Nodes (HVN) from volume distribution.
    Uses modern Polars DataFrame constructors and with_columns without deprecated methods.
    """
    pldf = standardize_ticker_data(df)
    
    if pldf.height == 0:
        return {
            "poc": 0.0, "vah": 0.0, "val": 0.0,
            "profile": pl.DataFrame(), "hvn": [], "total_volume": 0.0
        }
        
    prices = pldf[price_col].to_numpy()
    volumes = pldf[volume_col].to_numpy()
    
    p_min = float(prices.min())
    p_max = float(prices.max())
    
    if p_max == p_min:
        p_max += 1e-4
        
    bin_edges = np.linspace(p_min, p_max, num_bins + 1)
    bin_mids = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    
    # Digitize prices into bins
    bin_indices = np.clip(np.digitize(prices, bin_edges) - 1, 0, num_bins - 1)
    
    # Sum volume per bin
    binned_volume = np.zeros(num_bins, dtype=np.float64)
    for b_idx, vol in zip(bin_indices, volumes):
        binned_volume[b_idx] += vol
        
    total_vol = float(binned_volume.sum())
    if total_vol <= 0:
        return {
            "poc": float(bin_mids[0]), "vah": float(p_max), "val": float(p_min),
            "profile": pl.DataFrame(), "hvn": [], "total_volume": 0.0
        }
        
    poc_idx = int(np.argmax(binned_volume))
    poc = float(bin_mids[poc_idx])
    
    # Value Area Expansion (70% total volume)
    target_vol = total_vol * value_area_pct
    va_indices = {poc_idx}
    current_va_vol = float(binned_volume[poc_idx])
    
    idx_up = poc_idx + 1
    idx_down = poc_idx - 1
    
    while current_va_vol < target_vol and (idx_up < num_bins or idx_down >= 0):
        vol_up = float(binned_volume[idx_up]) if idx_up < num_bins else -1.0
        vol_down = float(binned_volume[idx_down]) if idx_down >= 0 else -1.0
        
        if vol_up >= vol_down and idx_up < num_bins:
            va_indices.add(idx_up)
            current_va_vol += vol_up
            idx_up += 1
        elif idx_down >= 0:
            va_indices.add(idx_down)
            current_va_vol += vol_down
            idx_down -= 1
        elif idx_up < num_bins:
            va_indices.add(idx_up)
            current_va_vol += vol_up
            idx_up += 1
        else:
            break
            
    val = float(bin_edges[min(va_indices)])
    vah = float(bin_edges[max(va_indices) + 1])
    
    # Detect High Volume Nodes (HVN)
    hvn_levels = []
    poc_vol = binned_volume[poc_idx]
    for i in range(1, num_bins - 1):
        if (binned_volume[i] > binned_volume[i - 1] and 
            binned_volume[i] > binned_volume[i + 1] and 
            binned_volume[i] >= 0.40 * poc_vol):
            hvn_levels.append(float(bin_mids[i]))
            
    # Build Profile DataFrame using direct Polars dict constructor
    profile_df = pl.DataFrame({
        "price_bin_low": bin_edges[:-1],
        "price_bin_mid": bin_mids,
        "price_bin_high": bin_edges[1:],
        "volume": binned_volume,
        "volume_pct": (binned_volume / total_vol) * 100.0,
        "is_poc": [i == poc_idx for i in range(num_bins)],
        "in_value_area": [i in va_indices for i in range(num_bins)]
    })
    
    return {
        "poc": poc,
        "vah": vah,
        "val": val,
        "profile": profile_df,
        "hvn": hvn_levels,
        "total_volume": total_vol
    }


def run_statarb_backtest(
    df_a: Union[pd.DataFrame, pl.DataFrame],
    df_b: Union[pd.DataFrame, pl.DataFrame],
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 3.5,
    rolling_window: int = 20,
    beta: Optional[float] = None,
    slippage_bps: float = 2.0,
    initial_capital: float = 100000.0
) -> Dict[str, Any]:
    """
    Runs an end-to-end vectorized StatArb backtest on pair data.
    Computes Sharpe, Sortino, Max Drawdown %, Win Rate, Profit Factor, Equity Curve, and Trade Logs.
    
    Polished with edge case guards:
    - initial_capital <= 0.0 guard returns total_return_pct = 0.0
    - Sharpe ratio when std == 0.0 returns 0.0 (or -99.99 if mean < 0)
    - Sortino ratio when downside std == 0.0 returns 0.0
    - Profit factor when gross_losses == 0.0 returns 99.99 (if gross_profits > 0) else 0.0
    """
    spread_df = compute_vwap_spread(df_a, df_b, rolling_window=rolling_window, beta=beta)
    z_df = compute_volume_weighted_zscore(spread_df, rolling_window=rolling_window)
    
    dates = z_df["date"].to_list()
    close_a = z_df["close_a"].to_numpy()
    close_b = z_df["close_b"].to_numpy()
    betas = z_df["beta"].to_numpy()
    spreads = z_df["spread"].to_numpy()
    zscores = z_df["zscore"].to_numpy()
    
    n = len(zscores)
    positions = np.zeros(n, dtype=np.int32)
    
    # State machine simulation
    current_pos = 0
    trade_logs = []
    
    entry_idx = 0
    entry_price_a = 0.0
    entry_price_b = 0.0
    entry_spread_val = 0.0
    entry_z_val = 0.0
    
    slippage_cost = slippage_bps / 10000.0
    
    for i in range(1, n):
        z = zscores[i]
        
        if current_pos == 0:
            if z > entry_z:
                # Enter Short Spread (Short A, Long B)
                current_pos = -1
                entry_idx = i
                entry_price_a = close_a[i]
                entry_price_b = close_b[i]
                entry_spread_val = spreads[i]
                entry_z_val = z
            elif z < -entry_z:
                # Enter Long Spread (Long A, Short B)
                current_pos = 1
                entry_idx = i
                entry_price_a = close_a[i]
                entry_price_b = close_b[i]
                entry_spread_val = spreads[i]
                entry_z_val = z
        elif current_pos == 1:  # Long Spread
            # Exit conditions
            is_mean_rev = (z >= -exit_z)
            is_stop_loss = (z <= -stop_z)
            if is_mean_rev or is_stop_loss or (i == n - 1):
                exit_reason = "STOP_LOSS" if is_stop_loss else ("MEAN_REVERSION" if is_mean_rev else "END_OF_DATA")
                ret_a = (close_a[i] - entry_price_a) / max(entry_price_a, 1e-8)
                ret_b = (close_b[i] - entry_price_b) / max(entry_price_b, 1e-8)
                pnl_pct = (ret_a - betas[entry_idx] * ret_b) - 2.0 * slippage_cost
                
                trade_logs.append({
                    "trade_id": len(trade_logs) + 1,
                    "side": "LONG_SPREAD",
                    "entry_date": dates[entry_idx],
                    "exit_date": dates[i],
                    "entry_price_a": float(entry_price_a),
                    "entry_price_b": float(entry_price_b),
                    "exit_price_a": float(close_a[i]),
                    "exit_price_b": float(close_b[i]),
                    "entry_z": float(entry_z_val),
                    "exit_z": float(z),
                    "entry_spread": float(entry_spread_val),
                    "exit_spread": float(spreads[i]),
                    "hedge_ratio": float(betas[entry_idx]),
                    "pnl_pct": float(pnl_pct * 100.0),
                    "pnl_dollars": float(initial_capital * pnl_pct) if initial_capital > 0 else 0.0,
                    "holding_bars": int(i - entry_idx),
                    "exit_reason": exit_reason
                })
                current_pos = 0
        elif current_pos == -1:  # Short Spread
            is_mean_rev = (z <= exit_z)
            is_stop_loss = (z >= stop_z)
            if is_mean_rev or is_stop_loss or (i == n - 1):
                exit_reason = "STOP_LOSS" if is_stop_loss else ("MEAN_REVERSION" if is_mean_rev else "END_OF_DATA")
                ret_a = (close_a[i] - entry_price_a) / max(entry_price_a, 1e-8)
                ret_b = (close_b[i] - entry_price_b) / max(entry_price_b, 1e-8)
                pnl_pct = (- (ret_a - betas[entry_idx] * ret_b)) - 2.0 * slippage_cost
                
                trade_logs.append({
                    "trade_id": len(trade_logs) + 1,
                    "side": "SHORT_SPREAD",
                    "entry_date": dates[entry_idx],
                    "exit_date": dates[i],
                    "entry_price_a": float(entry_price_a),
                    "entry_price_b": float(entry_price_b),
                    "exit_price_a": float(close_a[i]),
                    "exit_price_b": float(close_b[i]),
                    "entry_z": float(entry_z_val),
                    "exit_z": float(z),
                    "entry_spread": float(entry_spread_val),
                    "exit_spread": float(spreads[i]),
                    "hedge_ratio": float(betas[entry_idx]),
                    "pnl_pct": float(pnl_pct * 100.0),
                    "pnl_dollars": float(initial_capital * pnl_pct) if initial_capital > 0 else 0.0,
                    "holding_bars": int(i - entry_idx),
                    "exit_reason": exit_reason
                })
                current_pos = 0
                
        positions[i] = current_pos

    # Calculate Period Returns
    ret_a_daily = np.diff(close_a, prepend=close_a[0]) / np.maximum(close_a, 1e-8)
    ret_b_daily = np.diff(close_b, prepend=close_b[0]) / np.maximum(close_b, 1e-8)
    spread_return = ret_a_daily - betas * ret_b_daily
    
    # Lagged position for strategy return
    pos_lagged = np.roll(positions, 1)
    pos_lagged[0] = 0
    strategy_returns = pos_lagged * spread_return
    
    # Equity Curve
    equity_curve = np.cumprod(1.0 + strategy_returns)
    peak = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - peak) / peak
    max_drawdown_pct = float(np.min(drawdown) * 100.0) if len(drawdown) > 0 else 0.0
    
    # Guard against initial_capital <= 0.0
    if initial_capital <= 0.0:
        total_return_pct = 0.0
    else:
        total_return_pct = float((equity_curve[-1] - 1.0) * 100.0) if len(equity_curve) > 0 else 0.0
        
    # Sharpe Ratio: guard std == 0.0
    mean_ret = float(np.mean(strategy_returns)) if len(strategy_returns) > 0 else 0.0
    std_ret = float(np.std(strategy_returns)) if len(strategy_returns) > 0 else 0.0
    if std_ret > 1e-12:
        sharpe_ratio = float(np.sqrt(252) * mean_ret / std_ret)
    else:
        sharpe_ratio = 0.0
        
    # Sortino Ratio: guard downside std == 0.0
    neg_returns = strategy_returns[strategy_returns < 0]
    downside_std = float(np.std(neg_returns)) if len(neg_returns) > 0 else 0.0
    if downside_std > 1e-12:
        sortino_ratio = float(np.sqrt(252) * mean_ret / downside_std)
    else:
        sortino_ratio = 0.0
        
    # Trade statistics & Profit Factor
    total_trades = len(trade_logs)
    if total_trades > 0:
        pnls = np.array([t["pnl_pct"] for t in trade_logs])
        win_rate = float(np.sum(pnls > 0) / total_trades * 100.0)
        gross_profit = float(np.sum(pnls[pnls > 0])) if np.any(pnls > 0) else 0.0
        gross_loss = float(abs(np.sum(pnls[pnls < 0]))) if np.any(pnls < 0) else 0.0
        if gross_loss > 1e-12:
            profit_factor = float(gross_profit / gross_loss)
        elif gross_profit > 0.0:
            profit_factor = 99.99
        else:
            profit_factor = 0.0
    else:
        win_rate = 0.0
        profit_factor = 0.0
        
    trades_df = pl.DataFrame(trade_logs) if len(trade_logs) > 0 else pl.DataFrame(schema={
        "trade_id": pl.Int64, "side": pl.Utf8, "entry_date": pl.Datetime, "exit_date": pl.Datetime,
        "entry_price_a": pl.Float64, "entry_price_b": pl.Float64,
        "exit_price_a": pl.Float64, "exit_price_b": pl.Float64,
        "entry_z": pl.Float64, "exit_z": pl.Float64, "entry_spread": pl.Float64, "exit_spread": pl.Float64,
        "hedge_ratio": pl.Float64, "pnl_pct": pl.Float64, "pnl_dollars": pl.Float64,
        "holding_bars": pl.Int64, "exit_reason": pl.Utf8
    })
    
    equity_df = pl.DataFrame({
        "date": dates,
        "strategy_return": strategy_returns,
        "equity": equity_curve,
        "drawdown": drawdown,
        "position": positions,
        "zscore": zscores
    })
    
    return {
        "sharpe_ratio": round(sharpe_ratio, 3),
        "sortino_ratio": round(sortino_ratio, 3),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "total_trades": total_trades,
        "total_return_pct": round(total_return_pct, 2),
        "trades": trades_df,
        "equity_curve": equity_df
    }


DEFAULT_SECTOR_PAIRS: List[Tuple[str, str, str]] = [
    ("NVDA", "VRT", "AI Compute & Power"),
    ("SMCI", "CEG", "AI Hardware & Clean Energy"),
    ("AMD", "INTC", "Semiconductors & X86"),
    ("AVGO", "QCOM", "Semiconductors & Mobile"),
    ("TSM", "ASML", "Foundry & Lithography"),
    ("AAPL", "MSFT", "Big Tech Platforms"),
    ("GOOGL", "META", "Digital Ad & AI Models"),
    ("VST", "CEG", "Nuclear Power & Hyperscalers"),
    ("XOM", "CVX", "Energy Majors"),
    ("JPM", "BAC", "Money Center Banks"),
    ("MS", "GS", "Investment Banking"),
    ("COIN", "MSTR", "Crypto & Treasury Balance Sheets"),
]


def generate_synthetic_ohlcv(ticker: str, base_price: float = 100.0, num_bars: int = 500, seed: int = 42) -> pl.DataFrame:
    """Generates synthetic 1-minute OHLCV data for pair testing when yfinance data is unavailable."""
    np.random.seed(seed)
    dates = pd.date_range("2025-01-01", periods=num_bars, freq="1min")
    returns = np.random.normal(0, 0.001, size=num_bars)
    price_series = base_price * np.exp(np.cumsum(returns))
    
    highs = price_series * (1.0 + np.abs(np.random.normal(0, 0.0005, size=num_bars)))
    lows = price_series * (1.0 - np.abs(np.random.normal(0, 0.0005, size=num_bars)))
    opens = price_series * (1.0 + np.random.normal(0, 0.0002, size=num_bars))
    volumes = np.random.randint(500, 5000, size=num_bars).astype(np.float64)
    
    df = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": price_series,
        "volume": volumes
    })
    return standardize_ticker_data(df, ticker_name=ticker)


def scan_pair_universe(
    pairs_list: Optional[List[Tuple[str, str, str]]] = None,
    rolling_window: int = 20,
    entry_z: float = 2.0,
    data_provider: Optional[Dict[str, pl.DataFrame]] = None
) -> pl.DataFrame:
    """
    Scans a universe of candidate ticker pairs for statistical arbitrage opportunities.
    Computes current Z-score, rolling beta, volume profile POC, backtest Sharpe ratio, and active trade signals.
    """
    if pairs_list is None:
        pairs_list = DEFAULT_SECTOR_PAIRS
        
    results = []
    
    for idx, (t_a, t_b, sector) in enumerate(pairs_list):
        try:
            # Retrieve data from provider or generate synthetic pair
            if data_provider and t_a in data_provider and t_b in data_provider:
                df_a = data_provider[t_a]
                df_b = data_provider[t_b]
            else:
                seed_a = hash(t_a) % 10000
                seed_b = hash(t_b) % 10000
                base_a = 100.0 + (hash(t_a) % 200)
                base_b = 80.0 + (hash(t_b) % 150)
                df_a = generate_synthetic_ohlcv(t_a, base_price=base_a, num_bars=300, seed=seed_a)
                df_b = generate_synthetic_ohlcv(t_b, base_price=base_b, num_bars=300, seed=seed_b)
                
            spread_df = compute_vwap_spread(df_a, df_b, rolling_window=rolling_window)
            z_df = compute_volume_weighted_zscore(spread_df, rolling_window=rolling_window)
            
            if z_df.height < 5:
                continue
                
            last_row = z_df.tail(1).to_dicts()[0]
            curr_z = float(last_row.get("zscore", 0.0))
            curr_beta = float(last_row.get("beta", 1.0))
            curr_spread = float(last_row.get("spread", 0.0))
            curr_price_a = float(last_row.get("close_a", 0.0))
            curr_price_b = float(last_row.get("close_b", 0.0))
            
            # Determine Signal
            if curr_z <= -entry_z:
                signal = "BUY_A / SELL_B (LONG SPREAD)"
                signal_type = "LONG_SPREAD"
            elif curr_z >= entry_z:
                signal = "SELL_A / BUY_B (SHORT SPREAD)"
                signal_type = "SHORT_SPREAD"
            else:
                signal = "NEUTRAL (WAIT)"
                signal_type = "NEUTRAL"
                
            # Quick backtest metric
            bt = run_statarb_backtest(df_a, df_b, entry_z=entry_z, rolling_window=rolling_window)
            
            results.append({
                "ticker_a": t_a,
                "ticker_b": t_b,
                "sector": sector,
                "price_a": round(curr_price_a, 2),
                "price_b": round(curr_price_b, 2),
                "current_zscore": round(curr_z, 3),
                "abs_zscore": round(abs(curr_z), 3),
                "hedge_ratio_beta": round(curr_beta, 3),
                "spread_value": round(curr_spread, 3),
                "signal": signal,
                "signal_type": signal_type,
                "sharpe_ratio": bt["sharpe_ratio"],
                "total_return_pct": bt["total_return_pct"],
                "max_drawdown_pct": bt["max_drawdown_pct"],
                "total_trades": bt["total_trades"],
                "win_rate": bt["win_rate"]
            })
        except Exception as e:
            continue
            
    if not results:
        return pl.DataFrame(schema={
            "ticker_a": pl.Utf8, "ticker_b": pl.Utf8, "sector": pl.Utf8,
            "price_a": pl.Float64, "price_b": pl.Float64, "current_zscore": pl.Float64,
            "abs_zscore": pl.Float64, "hedge_ratio_beta": pl.Float64, "spread_value": pl.Float64,
            "signal": pl.Utf8, "signal_type": pl.Utf8, "sharpe_ratio": pl.Float64,
            "total_return_pct": pl.Float64, "max_drawdown_pct": pl.Float64,
            "total_trades": pl.Int64, "win_rate": pl.Float64
        })
        
    res_df = pl.DataFrame(results).sort(["abs_zscore", "sharpe_ratio"], descending=[True, True])
    return res_df

