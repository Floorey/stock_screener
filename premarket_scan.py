#!/usr/bin/env python3
"""
Premarket-Scan (S&P 500 / Nasdaq 100) mit Aufbau von Stat-Arb-Paaren.

Ablauf:
  1. Futures-Kontext (ES=F, NQ=F) fuer die Regime-Einschaetzung der Nacht.
  2. Vorfilter der Index-Mitglieder nach durchschnittlichem Dollar-Volumen.
  3. Premarket-Bars (1m -> N-Minuten resampled), letzte K Kerzen, Ranking nach
     Volumen pro Minute.
  4. Fuer jeden Volumen-Leader die statistisch passende Gegenseite suchen und
     ein handelbares Paar mit volatilitaetsskalierten Schwellen bauen.

WICHTIG zur Methodik: Schritt 3 und Schritt 4 beantworten verschiedene Fragen.
Volumen sagt, wo heute Liquiditaet ist. Es sagt nichts darueber, ob zwei Titel
zueinander mean-reverten. Hohes Premarket-Volumen ist meist nachrichtengetrieben
und damit eher ein Warnsignal fuer Paar-Handel, weil genau dann die historische
Beziehung bricht. Deshalb wird die Gegenseite ueber Korrelation und
Mean-Reversion gewaehlt (StatisticalArbitrageLab), nicht ueber Volumen, und
jedes Paar bekommt ein Divergenz-Flag, wenn der Leader auf News gappt.

Aufrufe:
    python premarket_scan.py
    python premarket_scan.py --bars 10 --minutes 3 --top 3
    python premarket_scan.py --self-test        # ohne Netzwerk, synthetische Daten
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    from backports.zoneinfo import ZoneInfo  # type: ignore

ET = ZoneInfo("America/New_York")
PREMARKET_OPEN = dtime(4, 0)
REGULAR_OPEN = dtime(9, 30)

# Futures, die waehrend der US-Premarket-Phase durchhandeln.
FUTURES = {"ES=F": "S&P 500 E-mini", "NQ=F": "Nasdaq 100 E-mini"}


# --------------------------------------------------------------------------
# Sitzung / Zeitfenster
# --------------------------------------------------------------------------

def resolve_session_date(now: Optional[datetime] = None) -> Tuple[date, str]:
    """
    Liefert das Handelsdatum, dessen Premarket ausgewertet wird, plus eine
    Beschreibung. Am Wochenende oder nach Handelsschluss faellt der Scan auf die
    zuletzt verfuegbare Sitzung zurueck, damit der Lauf nie leer ausgeht.

    Feiertage sind bewusst nicht modelliert: liefert Yahoo fuer den Tag keine
    Bars, meldet der Scan das offen, statt einen Kalender zu erfinden.
    """
    now = now or datetime.now(ET)
    today = now.date()

    if today.weekday() >= 5:  # Samstag/Sonntag
        offset = today.weekday() - 4
        session = today - timedelta(days=offset)
        return session, f"Wochenende - nutze letzte Sitzung ({session:%d.%m.%Y})"

    if now.time() < PREMARKET_OPEN:
        session = today - timedelta(days=3 if today.weekday() == 0 else 1)
        return session, f"Vor Premarket-Start - nutze letzte Sitzung ({session:%d.%m.%Y})"

    if now.time() < REGULAR_OPEN:
        return today, f"Live-Premarket ({now:%H:%M} ET)"

    return today, f"Hauptsitzung laeuft/vorbei - Premarket von heute ({session_label(now)})"


def session_label(now: datetime) -> str:
    return f"{now:%d.%m.%Y}"


# --------------------------------------------------------------------------
# Datenbeschaffung
# --------------------------------------------------------------------------

def _download(tickers: List[str], **kwargs) -> pd.DataFrame:
    """Duenner yfinance-Wrapper, damit der Import lokal bleibt und testbar ist."""
    import yfinance as yf

    return yf.download(
        tickers,
        progress=False,
        auto_adjust=False,
        group_by="ticker",
        threads=True,
        **kwargs,
    )


def _extract(raw: pd.DataFrame, ticker: str, single: bool) -> Optional[pd.DataFrame]:
    """Holt den OHLCV-Block eines Tickers aus einer (ggf. MultiIndex-) Antwort."""
    if raw is None or raw.empty:
        return None
    try:
        df = raw if single else raw[ticker]
    except KeyError:
        return None
    if df is None or df.empty:
        return None
    df = df.dropna(how="all")
    return df if not df.empty else None


def fetch_intraday(tickers: List[str], days: int = 5, chunk: int = 40, pause: float = 0.6) -> Dict[str, pd.DataFrame]:
    """
    1-Minuten-Bars inklusive Pre-/Postmarket. Yahoo liefert 1m nur fuer die
    letzten ~7 Kalendertage, deshalb ist 'days' klein zu halten.
    """
    out: Dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        try:
            raw = _download(batch, period=f"{days}d", interval="1m", prepost=True)
        except Exception as exc:
            print(f"[Scanner] 1m-Abruf fuer Block {i // chunk + 1} fehlgeschlagen: {exc}")
            continue

        for tk in batch:
            df = _extract(raw, tk, single=len(batch) == 1)
            if df is not None:
                out[tk] = localize(df)
        if i + chunk < len(tickers):
            time.sleep(pause)
    return out


def localize(df: pd.DataFrame) -> pd.DataFrame:
    """Index auf US/Eastern normalisieren - alle Sitzungsgrenzen sind ET."""
    idx = df.index
    if getattr(idx, "tz", None) is None:
        df.index = idx.tz_localize("UTC").tz_convert(ET)
    else:
        df.index = idx.tz_convert(ET)
    return df


def resample_bars(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """
    1m -> N-Minuten. Yahoo kennt kein 3m-Intervall, deshalb wird lokal
    aggregiert; 'label/closed=left' haelt die Kerzen an :00/:03/:06 ausgerichtet.
    """
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    cols = {c: agg[c] for c in agg if c in df.columns}
    res = df.resample(f"{minutes}min", label="left", closed="left").agg(cols)
    return res.dropna(subset=["Close"])


def premarket_slice(df: pd.DataFrame, session: date) -> pd.DataFrame:
    """Nur Bars des Premarket-Fensters 04:00-09:30 ET am Sitzungstag."""
    mask = (
        (df.index.date == session)
        & (df.index.time >= PREMARKET_OPEN)
        & (df.index.time < REGULAR_OPEN)
    )
    return df.loc[mask]


# --------------------------------------------------------------------------
# Schritt 1: Futures-Kontext
# --------------------------------------------------------------------------

def futures_context(session: date, minutes: int) -> List[Dict[str, Any]]:
    """Overnight-Bewegung und realisierte Vola der Index-Futures."""
    rows: List[Dict[str, Any]] = []
    data = fetch_intraday(list(FUTURES), days=5)

    for symbol, name in FUTURES.items():
        df = data.get(symbol)
        if df is None or df.empty:
            rows.append({"Symbol": symbol, "Name": name, "Status": "keine Daten"})
            continue

        bars = resample_bars(df, minutes)
        overnight = bars[bars.index.date == session]
        if overnight.empty:
            overnight = bars[bars.index.date == bars.index.date.max()]

        first, last = overnight["Open"].iloc[0], overnight["Close"].iloc[-1]
        ret = overnight["Close"].pct_change().dropna()
        rows.append({
            "Symbol": symbol,
            "Name": name,
            "Status": "ok",
            "Move_%": round(float((last / first - 1) * 100), 3),
            # Bar-Vola auf Tagesbasis skaliert (390 Handelsminuten / Barlaenge).
            "RealVol_%": round(float(ret.std() * np.sqrt(390 / minutes) * 100), 3) if len(ret) > 2 else None,
            "Bars": int(len(overnight)),
        })
    return rows


# --------------------------------------------------------------------------
# Schritt 2+3: Vorfilter und Volumen-Ranking
# --------------------------------------------------------------------------

def prefilter_by_dollar_volume(tickers: List[str], keep: int, chunk: int = 100) -> List[str]:
    """
    Grobfilter ueber Tagesdaten: 1-Minuten-Abrufe fuer 600 Titel sind teuer und
    laufen in Yahoo-Limits. Premarket-Volumen konzentriert sich ohnehin in den
    liquiden Namen, der Filter kostet also kaum Trefferqualitaet.
    """
    scores: Dict[str, float] = {}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        try:
            raw = _download(batch, period="1mo", interval="1d")
        except Exception as exc:
            print(f"[Scanner] Tagesdaten-Block {i // chunk + 1} fehlgeschlagen: {exc}")
            continue
        for tk in batch:
            df = _extract(raw, tk, single=len(batch) == 1)
            if df is None or "Volume" not in df:
                continue
            dollar = (df["Close"] * df["Volume"]).tail(20).mean()
            if pd.notna(dollar) and dollar > 0:
                scores[tk] = float(dollar)

    ranked = sorted(scores, key=scores.get, reverse=True)[:keep]
    print(f"[Scanner] Vorfilter: {len(ranked)} von {len(tickers)} Titeln nach Dollar-Volumen behalten.")
    return ranked


def volume_rate_scan(
    tickers: List[str],
    session: date,
    bars: int,
    minutes: int,
) -> pd.DataFrame:
    """
    Kernkennzahl: Volumen pro Minute ueber die letzten 'bars' Kerzen des
    Premarkets. Pro Minute statt pro Kerze, damit die Zahl unabhaengig von der
    gewaehlten Barlaenge vergleichbar bleibt.
    """
    data = fetch_intraday(tickers, days=5)
    rows: List[Dict[str, Any]] = []

    for tk, df in data.items():
        pm = premarket_slice(resample_bars(df, minutes), session)
        if pm.empty:
            continue

        window = pm.tail(bars)
        span = max(len(window) * minutes, 1)
        shares = float(window["Volume"].sum())
        if shares <= 0:
            continue

        typical = (window["High"] + window["Low"] + window["Close"]) / 3
        dollar = float((typical * window["Volume"]).sum())
        first, last = float(window["Open"].iloc[0]), float(window["Close"].iloc[-1])
        ret = window["Close"].pct_change().dropna()

        rows.append({
            "Ticker": tk,
            "Shares/min": round(shares / span, 1),
            "USD/min": round(dollar / span, 1),
            "Volume": int(shares),
            "Bars": len(window),
            "ActiveBars": int((window["Volume"] > 0).sum()),
            "Move_%": round((last / first - 1) * 100, 3) if first else 0.0,
            "BarVol_%": round(float(ret.std() * 100), 3) if len(ret) > 2 else 0.0,
            "Last": round(last, 2),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("USD/min", ascending=False).reset_index(drop=True)
    # Anteil am Premarket-Dollarumsatz des gescannten Universums.
    df["Share_%"] = (df["USD/min"] / df["USD/min"].sum() * 100).round(2)
    return df


# --------------------------------------------------------------------------
# Schritt 4: Gegenseite und Paarbau
# --------------------------------------------------------------------------

def correlation_pool(
    leader: str,
    universe: List[str],
    lookback: str = "1y",
    keep: int = 12,
    chunk: int = 100,
) -> List[str]:
    """
    Kandidaten fuer die Gegenseite: Titel mit der hoechsten Korrelation der
    Tagesrenditen zum Leader. Renditen, nicht Preise - Preiskorrelation zweier
    steigender Reihen ist fast immer hoch und sagt nichts ueber die Beziehung.
    """
    pool = [t for t in universe if t != leader]
    closes: Dict[str, pd.Series] = {}

    for i in range(0, len(pool), chunk):
        batch = pool[i : i + chunk]
        try:
            raw = _download(batch + [leader], period=lookback, interval="1d")
        except Exception as exc:
            print(f"[Pairs] Korrelations-Block fehlgeschlagen: {exc}")
            continue
        for tk in batch + [leader]:
            df = _extract(raw, tk, single=False)
            if df is not None and "Close" in df:
                closes[tk] = df["Close"]

    if leader not in closes:
        return []

    frame = pd.DataFrame(closes).dropna(how="all")
    returns = frame.pct_change().dropna(how="all")
    if leader not in returns or len(returns) < 60:
        return []

    corr = returns.corrwith(returns[leader]).drop(labels=[leader], errors="ignore")
    return list(corr.dropna().sort_values(ascending=False).head(keep).index)


def choose_counterpart(leader: str, candidates: List[str], period: str = "1y") -> Optional[Dict[str, Any]]:
    """
    Bewertet jeden Kandidaten mit der bestehenden Eignungspruefung des Repos und
    nimmt den hoechsten Score. Bewusst wiederverwendet statt neu gebaut, damit
    Scanner und Arbitrage-Lab dieselbe Definition von Eignung benutzen.
    """
    from arbitrage_lab import StatisticalArbitrageLab

    best: Optional[Dict[str, Any]] = None
    for cand in candidates:
        try:
            res = StatisticalArbitrageLab.calculate_pair_suitability(leader, cand, period=period)
        except Exception:
            continue
        if res.get("status") != "success":
            continue
        if best is None or res["score"] > best["score"]:
            best = res
    return best


def build_pair(
    suitability: Dict[str, Any],
    leader_row: pd.Series,
    capital: float,
    risk_pct: float,
    window: int = 20,
) -> Dict[str, Any]:
    """
    Baut aus einer Eignungspruefung ein handelbares Paar: aktueller Z-Score,
    volatilitaetsskalierte Ein-/Ausstiegsschwellen und eine Stueckzahl, die sich
    am Risikobudget orientiert.

    "Vol-basiert" heisst hier: die Einstiegsschwelle ist nicht fix bei 2 Sigma,
    sondern waechst, wenn die juengste Spread-Vola ueber der laengerfristigen
    liegt. In unruhigen Phasen ist ein 2-Sigma-Ausschlag deutlich weniger
    aussagekraeftig als in ruhigen.
    """
    from arbitrage_lab import StatisticalArbitrageLab

    a, b = suitability["ticker_a"], suitability["ticker_b"]
    df = StatisticalArbitrageLab.fetch_pairs_data(a, b, period="6mo")
    beta = float(suitability["beta"])

    spread = df["Price_A"] - beta * df["Price_B"]
    mean, sigma = spread.rolling(window).mean(), spread.rolling(window).std()
    z = float(((spread - mean) / sigma).iloc[-1])
    sigma_now = float(sigma.iloc[-1])

    # Vola-Regime: kurzfristige gegen laengerfristige Spread-Schwankung.
    short_vol = float(spread.diff().tail(10).std())
    long_vol = float(spread.diff().tail(60).std())
    vol_ratio = short_vol / long_vol if long_vol > 0 else 1.0
    entry_z = round(2.0 * float(np.clip(vol_ratio, 0.75, 1.75)), 2)
    stop_z = round(entry_z + 1.5, 2)

    # Sizing: Stop-Distanz in Dollar je Stueck A -> Stueckzahl aus Risikobudget.
    risk_budget = capital * risk_pct
    stop_distance = max((stop_z - entry_z) * sigma_now, 0.01)
    qty_a = int(max(risk_budget / stop_distance, 0))
    qty_b = int(round(qty_a * beta))

    price_a = float(df["Price_A"].iloc[-1])
    price_b = float(df["Price_B"].iloc[-1])

    if z >= entry_z:
        direction = f"Spread verkaufen: SHORT {a} / LONG {b}"
    elif z <= -entry_z:
        direction = f"Spread kaufen: LONG {a} / SHORT {b}"
    else:
        direction = "kein Signal - Z-Score innerhalb der Schwelle"

    # Divergenz-Warnung: gappt der Leader stark relativ zu seiner Bar-Vola,
    # ist das meist eine Einzelnachricht und die Paarbeziehung gerade gebrochen.
    move = abs(float(leader_row.get("Move_%", 0.0)))
    bar_vol = float(leader_row.get("BarVol_%", 0.0))
    gap_ratio = move / bar_vol if bar_vol > 0 else 0.0
    news_flag = move >= 2.0 or gap_ratio >= 4.0

    return {
        "leader": a,
        "counterpart": b,
        "score": suitability["score"],
        "recommendation": suitability["recommendation"],
        "correlation": round(float(suitability["correlation"]), 4),
        "hedge_ratio_beta": round(beta, 4),
        "half_life_days": round(float(suitability["half_life"]), 2),
        "crossings_per_year": round(float(suitability["normalized_crossings_annual"]), 1),
        "z_score": round(z, 3),
        "spread_sigma": round(sigma_now, 4),
        "vol_ratio_10_60": round(vol_ratio, 3),
        "entry_z": entry_z,
        "stop_z": stop_z,
        "exit_z": 0.3,
        "direction": direction,
        "qty_a": qty_a,
        "qty_b": qty_b,
        "notional_a": round(qty_a * price_a, 2),
        "notional_b": round(qty_b * price_b, 2),
        "risk_budget": round(risk_budget, 2),
        "premarket_move_%": round(move, 3),
        "gap_vs_barvol": round(gap_ratio, 2),
        "divergence_warning": bool(news_flag),
    }


# --------------------------------------------------------------------------
# Ausgabe
# --------------------------------------------------------------------------

def render(result: Dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print(f"  PREMARKET-SCAN  |  {result['session']}  |  {result['session_note']}")
    print("=" * 78)

    print("\n--- Futures-Kontext ---")
    for row in result["futures"]:
        if row.get("Status") != "ok":
            print(f"  {row['Symbol']:6} {row['Name']:20} keine Daten")
        else:
            print(
                f"  {row['Symbol']:6} {row['Name']:20} "
                f"Move {row['Move_%']:+.2f}%   RealVol {row['RealVol_%']}%   Bars {row['Bars']}"
            )

    for index_name, table in result["scans"].items():
        print(f"\n--- {index_name}: Volumen/Zeit, letzte {result['bars']} x {result['minutes']}min ---")
        if table.empty:
            print("  keine Premarket-Bars gefunden")
            continue
        print(table.head(result["top"] * 3).to_string(index=False))

    print("\n--- Paare ---")
    if not result["pairs"]:
        print("  keine Paare gebildet")
    for i, p in enumerate(result["pairs"], 1):
        warn = "  [!] DIVERGENZRISIKO - Leader gappt, Beziehung moeglicherweise gebrochen" if p["divergence_warning"] else ""
        print(f"\n  {i}. {p['leader']} / {p['counterpart']}   Score {p['score']}/100 ({p['recommendation']}){warn}")
        print(f"     Korrelation {p['correlation']:.3f}   Beta {p['hedge_ratio_beta']:.4f}   "
              f"Halbwertszeit {p['half_life_days']:.1f}d   Kreuzungen/Jahr {p['crossings_per_year']:.0f}")
        print(f"     Z-Score {p['z_score']:+.2f}   Einstieg +/-{p['entry_z']}   Stop +/-{p['stop_z']}   "
              f"Ausstieg +/-{p['exit_z']}   VolRatio {p['vol_ratio_10_60']:.2f}")
        print(f"     {p['direction']}")
        print(f"     Groesse: {p['qty_a']} x {p['leader']} (${p['notional_a']:,.0f}) gegen "
              f"{p['qty_b']} x {p['counterpart']} (${p['notional_b']:,.0f})   Risiko ${p['risk_budget']:,.0f}")

    print("\n" + "=" * 78)


# --------------------------------------------------------------------------
# Orchestrierung
# --------------------------------------------------------------------------

def run(args: argparse.Namespace) -> Dict[str, Any]:
    from screener import fetch_nasdaq100_tickers, fetch_sp500_tickers

    session, note = resolve_session_date()
    print(f"[Scanner] Sitzung: {session:%d.%m.%Y} - {note}")

    universes = {
        "S&P 500": [t for t, _ in fetch_sp500_tickers()],
        "Nasdaq 100": [t for t, _ in fetch_nasdaq100_tickers()],
    }

    result: Dict[str, Any] = {
        "session": f"{session:%d.%m.%Y}",
        "session_note": note,
        "bars": args.bars,
        "minutes": args.minutes,
        "top": args.top,
        "futures": futures_context(session, args.minutes),
        "scans": {},
        "pairs": [],
    }

    leaders: List[Tuple[str, pd.Series, List[str]]] = []
    for index_name, tickers in universes.items():
        filtered = prefilter_by_dollar_volume(tickers, keep=args.prefilter)
        table = volume_rate_scan(filtered, session, args.bars, args.minutes)
        result["scans"][index_name] = table
        for _, row in table.head(args.top).iterrows():
            leaders.append((row["Ticker"], row, filtered))

    # Ueber beide Indizes hinweg die staerksten Leader nehmen, Duplikate raus.
    seen: set = set()
    ordered = sorted(leaders, key=lambda x: x[1]["USD/min"], reverse=True)
    picks = []
    for tk, row, pool in ordered:
        if tk in seen:
            continue
        seen.add(tk)
        picks.append((tk, row, pool))
        if len(picks) >= args.top:
            break

    for tk, row, pool in picks:
        print(f"[Pairs] Suche Gegenseite fuer {tk} ...")
        candidates = correlation_pool(tk, pool, keep=args.candidates)
        if not candidates:
            print(f"[Pairs] Keine Kandidaten fuer {tk} gefunden.")
            continue
        best = choose_counterpart(tk, candidates)
        if not best:
            print(f"[Pairs] Keine bewertbare Gegenseite fuer {tk}.")
            continue
        try:
            result["pairs"].append(build_pair(best, row, args.capital, args.risk))
        except Exception as exc:
            print(f"[Pairs] Paarbau {tk}/{best['ticker_b']} fehlgeschlagen: {exc}")

    return result


# --------------------------------------------------------------------------
# Selbsttest ohne Netzwerk
# --------------------------------------------------------------------------

def self_test() -> int:
    """
    Prueft die Rechenpfade mit synthetischen Bars. Kein Netzwerk, kein Yahoo -
    faengt Resampling-, Zeitzonen- und Ranking-Fehler ab, bevor der Scan
    morgens frueh gegen echte Daten laeuft.
    """
    print("[Selbsttest] Baue synthetische Premarket-Bars ...")
    session = date(2026, 8, 7)
    idx = pd.date_range(f"{session} 04:00", f"{session} 09:29", freq="1min", tz=ET)
    rng = np.random.default_rng(42)

    frames = {}
    for i, tk in enumerate(["AAA", "BBB", "CCC"]):
        price = 100 + np.cumsum(rng.normal(0, 0.05, len(idx)))
        vol = rng.integers(100, 1000, len(idx)) * (3 - i)
        frames[tk] = pd.DataFrame(
            {"Open": price, "High": price + 0.05, "Low": price - 0.05, "Close": price, "Volume": vol},
            index=idx,
        )

    failures = 0

    bars = resample_bars(frames["AAA"], 3)
    expected = len(idx) // 3
    if not (expected - 1 <= len(bars) <= expected + 1):
        print(f"  FEHLER Resampling: {len(bars)} Bars, erwartet ~{expected}")
        failures += 1
    else:
        print(f"  ok  Resampling 1m -> 3m: {len(bars)} Bars")

    if frames["AAA"]["Volume"].sum() != bars["Volume"].sum():
        print("  FEHLER Resampling: Volumen geht beim Aggregieren verloren")
        failures += 1
    else:
        print("  ok  Volumen bleibt beim Resampling erhalten")

    pm = premarket_slice(bars, session)
    if pm.empty or pm.index.time.max() >= REGULAR_OPEN:
        print("  FEHLER Premarket-Fenster: Bars ausserhalb 04:00-09:30")
        failures += 1
    else:
        print(f"  ok  Premarket-Fenster: {len(pm)} Bars, letzte {pm.index[-1]:%H:%M}")

    # Ranking gegen den Netzwerkpfad vorbei testen.
    original = globals()["fetch_intraday"]
    globals()["fetch_intraday"] = lambda tickers, **kw: {t: frames[t] for t in tickers if t in frames}
    try:
        table = volume_rate_scan(["AAA", "BBB", "CCC"], session, bars=10, minutes=3)
    finally:
        globals()["fetch_intraday"] = original

    if table.empty or list(table["Ticker"])[0] != "AAA":
        print(f"  FEHLER Ranking: erwartet AAA vorn, bekam {list(table['Ticker']) if not table.empty else 'nichts'}")
        failures += 1
    else:
        print(f"  ok  Ranking nach USD/min: {' > '.join(table['Ticker'])}")

    if not table.empty:
        window_minutes = 10 * 3
        recomputed = frames["AAA"].tail(window_minutes)["Volume"].sum() / window_minutes
        if abs(table.loc[0, "Shares/min"] - recomputed) > 1.0:
            print(f"  FEHLER Volumenrate: {table.loc[0, 'Shares/min']} vs erwartet {recomputed:.1f}")
            failures += 1
        else:
            print(f"  ok  Volumenrate stimmt mit Direktrechnung ueberein ({recomputed:.1f}/min)")

        if abs(table["Share_%"].sum() - 100.0) > 0.1:
            print(f"  FEHLER Anteile summieren auf {table['Share_%'].sum()}")
            failures += 1
        else:
            print("  ok  Anteile summieren auf 100%")

    sess, note = resolve_session_date(datetime(2026, 8, 9, 10, 0, tzinfo=ET))  # Sonntag
    if sess != date(2026, 8, 7):
        print(f"  FEHLER Wochenend-Fallback: {sess}, erwartet 2026-08-07")
        failures += 1
    else:
        print(f"  ok  Wochenend-Fallback -> {sess} ({note})")

    failures += _self_test_pair()

    print(f"\n[Selbsttest] {'bestanden' if failures == 0 else f'{failures} Fehler'}")
    return 1 if failures else 0


def _self_test_pair() -> int:
    """
    Paarbau gegen eine synthetische, bewusst mean-revertende Preisreihe. Deckt
    Beta, Z-Score, Vola-Skalierung und Sizing ab - der Teil, den der Live-Lauf
    erst morgens frueh testen wuerde.
    """
    from arbitrage_lab import StatisticalArbitrageLab

    rng = np.random.default_rng(7)
    n = 180
    base = 100 + np.cumsum(rng.normal(0, 0.8, n))
    # B folgt A mit Beta 0.5 plus stationaerem Rauschen -> echte Mean Reversion.
    noise = np.zeros(n)
    for i in range(1, n):
        noise[i] = 0.8 * noise[i - 1] + rng.normal(0, 0.5)
    frame = pd.DataFrame(
        {"Price_A": base + noise, "Price_B": (base - 50) / 0.5},
        index=pd.date_range("2026-01-01", periods=n, freq="D"),
    )

    original = StatisticalArbitrageLab.fetch_pairs_data
    StatisticalArbitrageLab.fetch_pairs_data = staticmethod(lambda a, b, period="60d": frame.copy())
    try:
        suitability = StatisticalArbitrageLab.calculate_pair_suitability("AAA", "BBB", period="6mo")
        if suitability.get("status") != "success":
            print(f"  FEHLER Eignungspruefung: {suitability.get('message')}")
            return 1

        leader_row = pd.Series({"Move_%": 0.4, "BarVol_%": 0.3})
        pair = build_pair(suitability, leader_row, capital=100_000.0, risk_pct=0.01)
    except Exception as exc:
        print(f"  FEHLER Paarbau warf: {exc}")
        return 1
    finally:
        StatisticalArbitrageLab.fetch_pairs_data = original

    problems = 0
    if not (0.3 <= pair["hedge_ratio_beta"] <= 0.7):
        print(f"  FEHLER Beta {pair['hedge_ratio_beta']}, erwartet ~0.5")
        problems += 1
    if pair["qty_a"] <= 0 or pair["qty_b"] <= 0:
        print(f"  FEHLER Sizing ergibt {pair['qty_a']}/{pair['qty_b']} Stueck")
        problems += 1
    if not (1.5 <= pair["entry_z"] <= 3.5) or pair["stop_z"] <= pair["entry_z"]:
        print(f"  FEHLER Schwellen: Einstieg {pair['entry_z']}, Stop {pair['stop_z']}")
        problems += 1
    if pair["divergence_warning"]:
        print("  FEHLER Divergenz-Flag bei ruhigem Leader gesetzt")
        problems += 1

    # Gegenprobe: ein gappender Leader muss das Flag ausloesen.
    StatisticalArbitrageLab.fetch_pairs_data = staticmethod(lambda a, b, period="60d": frame.copy())
    try:
        gapped = build_pair(suitability, pd.Series({"Move_%": 5.2, "BarVol_%": 0.3}), 100_000.0, 0.01)
    finally:
        StatisticalArbitrageLab.fetch_pairs_data = original
    if not gapped["divergence_warning"]:
        print("  FEHLER Divergenz-Flag fehlt bei 5.2% Gap")
        problems += 1

    if problems == 0:
        print(f"  ok  Paarbau: Beta {pair['hedge_ratio_beta']:.3f}, Z {pair['z_score']:+.2f}, "
              f"Einstieg +/-{pair['entry_z']}, {pair['qty_a']}/{pair['qty_b']} Stueck")
        print("  ok  Divergenz-Flag reagiert auf Gap")
    return problems


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bars", type=int, default=10, help="Anzahl Kerzen im Messfenster (Standard 10)")
    p.add_argument("--minutes", type=int, default=3, help="Kerzenlaenge in Minuten (Standard 3)")
    p.add_argument("--top", type=int, default=3, help="Anzahl Leader und damit Paare (Standard 3)")
    p.add_argument("--prefilter", type=int, default=150, help="Titel je Index nach Dollar-Volumen-Vorfilter")
    p.add_argument("--candidates", type=int, default=12, help="Korrelations-Kandidaten je Leader")
    p.add_argument("--capital", type=float, default=100_000.0, help="Kapitalbasis fuer das Sizing")
    p.add_argument("--risk", type=float, default=0.01, help="Risikobudget je Paar als Anteil (Standard 1%%)")
    p.add_argument("--json", metavar="PFAD", help="Ergebnis zusaetzlich als JSON speichern")
    p.add_argument("--self-test", action="store_true", help="Rechenpfade offline pruefen")
    args = p.parse_args()

    if args.self_test:
        return self_test()

    result = run(args)
    render(result)

    if args.json:
        serializable = dict(result)
        serializable["scans"] = {k: v.to_dict("records") for k, v in result["scans"].items()}
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(serializable, fh, indent=2, ensure_ascii=False)
        print(f"[Scanner] Ergebnis gespeichert: {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
