"""
algo_router.py — Analytischer Check, Regime-Klassifikation und Trigger-Layer.

Beantwortet die Frage: "Welcher Algorithmus darf jetzt laufen — Falcone-Engine
(VPEI/Volumen-Spike), Stat-Arb-Pairs, Premarket-Volume-Rate, TWAP/VWAP-Execution
oder Hedging — und welcher ist gesperrt?"

Zwei Ebenen:

1. ROUTING (Makro-Ebene): `route()` erstellt einen Regime-Snapshot (Session-Phase,
   VIX, Realized Vol, Kaufman Efficiency Ratio, Breadth, Rates) und bewertet jeden
   registrierten Algorithmus gegen HARD GATES (K.o.-Kriterien) und ein
   transparentes Score-Modell. Ergebnis: GO / CONDITIONAL / BLOCKED je Algo.

2. PREFLIGHT (Signal-Ebene): `preflight_signals()` prüft konkrete Falcone-Signale
   vor der Ausführung auf Bar-Frische, Liquidität, RR-Plausibilität,
   Positionsgrößen-Kappung (inkl. der Kontrakt-Rundung in execute_signal),
   Doppelsignale/Cooldown und bestehende Exposure.

Dieses Modul feuert NIEMALS selbst Orders ab. Es liefert ausschließlich Urteile;
die Ausführung bleibt in `falcone_server.execute_signal` / den bestehenden Pfaden.
"""

import os
import re
import sys
import math
import datetime
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from alpaca_trader import is_alpaca_configured, get_account_info, get_positions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FALCONE_LOG = os.path.join(BASE_DIR, "falcone_engine.log")

# Cache für Marktdaten (yfinance ist langsam, Streamlit rendert häufig neu)
_SNAPSHOT_TTL_SECONDS = 120
_CACHE: Dict[str, Any] = {}

# --------------------------------------------------------------------------
# Risiko-Parameter (Spiegel der Werte in falcone_server.execute_signal)
# --------------------------------------------------------------------------
RISK_PCT_NASDAQ = 0.01
RISK_PCT_RUSSELL = 0.005
MAX_POSITION_PCT = 0.15          # harte Kappe je Einzelposition
MAX_GROSS_EXPOSURE_PCT = 1.50    # Bruttoexposure-Limit fürs Gesamtdepot
CONTRACT_MULTIPLIER = 100        # Synthetic Swap = 1 Kontrakt ≈ 100 Aktien Delta

# Preflight-Schwellen
MAX_BAR_AGE_MIN = 12.0           # 5m-Bar darf max. so alt sein
MIN_BAR_DOLLAR_VOLUME = 250_000  # USD-Umsatz der Signal-Kerze
MIN_PRICE = 5.0                  # keine Penny-Stocks
MIN_RR = 1.8
MIN_STOP_PCT = 0.30              # Stop-Distanz in % vom Kurs
MAX_STOP_PCT = 8.00
COOLDOWN_MINUTES = 30            # kein zweites Signal je Ticker in diesem Fenster


# ==========================================================================
# Session / Zeit
# ==========================================================================

def get_ny_now() -> pd.Timestamp:
    """Aktuelle Zeit an der NYSE (DST-korrekt über die IANA-Zone)."""
    try:
        return pd.Timestamp.now(tz="America/New_York")
    except Exception:
        # Fallback ohne tz-Datenbank: grobe UTC-5-Näherung
        return pd.Timestamp.utcnow() - pd.Timedelta(hours=5)


SESSION_PHASES = {
    "WEEKEND": "Wochenende — keine US-Kassamärkte",
    "OVERNIGHT": "Overnight (20:00–04:00 ET) — nur Futures",
    "PRE": "Premarket (04:00–09:30 ET)",
    "OPEN_DRIVE": "Opening Drive (09:30–11:00 ET)",
    "MIDDAY": "Midday Lull (11:00–14:00 ET)",
    "POWER_HOUR": "Power Hour (14:00–16:00 ET)",
    "AFTER": "After Hours (16:00–20:00 ET)",
}


def get_session_phase(now: Optional[pd.Timestamp] = None) -> Dict[str, Any]:
    """Klassifiziert die aktuelle US-Handelsphase — Basis fast aller Trigger."""
    now = now or get_ny_now()
    minutes = now.hour * 60 + now.minute

    if now.weekday() >= 5:
        phase = "WEEKEND"
    elif minutes < 4 * 60:
        phase = "OVERNIGHT"
    elif minutes < 9 * 60 + 30:
        phase = "PRE"
    elif minutes < 11 * 60:
        phase = "OPEN_DRIVE"
    elif minutes < 14 * 60:
        phase = "MIDDAY"
    elif minutes < 16 * 60:
        phase = "POWER_HOUR"
    elif minutes < 20 * 60:
        phase = "AFTER"
    else:
        phase = "OVERNIGHT"

    cash_open = phase in ("OPEN_DRIVE", "MIDDAY", "POWER_HOUR")
    return {
        "phase": phase,
        "label": SESSION_PHASES[phase],
        "ny_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "cash_session_open": cash_open,
        "minutes_since_open": minutes - (9 * 60 + 30) if cash_open else None,
        "minutes_to_close": (16 * 60) - minutes if cash_open else None,
    }


# ==========================================================================
# Regime-Snapshot
# ==========================================================================

def _efficiency_ratio(closes: pd.Series, window: int = 20) -> Optional[float]:
    """
    Kaufman Efficiency Ratio: |Netto-Bewegung| / Summe(|Tagesbewegungen|).

    Nahe 1 = sauberer Trend (Momentum-Algorithmen), nahe 0 = Sägezahn
    (Mean-Reversion / Stat-Arb). Der zentrale Diskriminator dieses Routers.
    """
    if closes is None or len(closes) < window + 1:
        return None
    seg = closes.iloc[-(window + 1):]
    net = abs(float(seg.iloc[-1]) - float(seg.iloc[0]))
    path = float(seg.diff().abs().sum())
    if path <= 0:
        return None
    return net / path


def _pct_change(series: pd.Series, periods: int) -> Optional[float]:
    if series is None or len(series) <= periods:
        return None
    prev = float(series.iloc[-1 - periods])
    if prev == 0:
        return None
    return (float(series.iloc[-1]) / prev - 1.0) * 100.0


def _download_closes(symbols: List[str], period: str = "6mo") -> Dict[str, pd.Series]:
    """Tagesschlusskurse je Symbol; fehlende Symbole werden still ausgelassen."""
    out: Dict[str, pd.Series] = {}
    try:
        raw = yf.download(symbols, period=period, interval="1d",
                          group_by="ticker", progress=False, auto_adjust=False)
    except Exception:
        raw = pd.DataFrame()

    for sym in symbols:
        try:
            if isinstance(raw.columns, pd.MultiIndex) and sym in raw.columns.levels[0]:
                s = raw[sym]["Close"].dropna()
            elif not raw.empty and "Close" in raw.columns and len(symbols) == 1:
                s = raw["Close"].dropna()
            else:
                s = pd.Series(dtype=float)
            if s.empty:
                s = yf.Ticker(sym).history(period=period)["Close"].dropna()
            if not s.empty:
                out[sym] = s
        except Exception:
            continue
    return out


def fetch_regime_snapshot(force: bool = False) -> Dict[str, Any]:
    """
    Sammelt alle Marktvariablen, auf denen die Trigger-Logik aufsetzt.
    Ergebnis wird 120 Sekunden gecached.
    """
    cached = _CACHE.get("snapshot")
    if cached and not force:
        ts, data = cached
        if (datetime.datetime.now() - ts).total_seconds() < _SNAPSHOT_TTL_SECONDS:
            return data

    closes = _download_closes(["^VIX", "SPY", "QQQ", "IWM", "^TNX"])
    spy = closes.get("SPY")
    vix = closes.get("^VIX")
    iwm = closes.get("IWM")
    qqq = closes.get("QQQ")
    tnx = closes.get("^TNX")

    snap: Dict[str, Any] = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_ok": spy is not None and vix is not None,
        "vix": float(vix.iloc[-1]) if vix is not None and len(vix) else None,
        "vix_chg_5d_pct": _pct_change(vix, 5) if vix is not None else None,
        "vix_pct_rank_1y": None,
        "spy_last": float(spy.iloc[-1]) if spy is not None and len(spy) else None,
        "spy_sma20": None,
        "spy_sma50": None,
        "spy_dist_sma50_pct": None,
        "realized_vol_20d": None,
        "efficiency_ratio": None,
        "breadth_iwm_vs_spy_20d": None,
        "qqq_vs_spy_20d": None,
        "tnx": float(tnx.iloc[-1]) if tnx is not None and len(tnx) else None,
        "tnx_chg_5d_bp": None,
    }

    if vix is not None and len(vix) >= 60:
        window = vix.iloc[-252:] if len(vix) >= 252 else vix
        snap["vix_pct_rank_1y"] = float((window <= vix.iloc[-1]).mean() * 100.0)

    if spy is not None and len(spy) >= 51:
        sma20 = float(spy.rolling(20).mean().iloc[-1])
        sma50 = float(spy.rolling(50).mean().iloc[-1])
        last = float(spy.iloc[-1])
        snap["spy_sma20"] = sma20
        snap["spy_sma50"] = sma50
        snap["spy_dist_sma50_pct"] = (last / sma50 - 1.0) * 100.0 if sma50 else None
        rets = spy.pct_change().dropna().iloc[-20:]
        if len(rets) >= 10:
            snap["realized_vol_20d"] = float(rets.std() * math.sqrt(252) * 100.0)
        snap["efficiency_ratio"] = _efficiency_ratio(spy, 20)

    if spy is not None and iwm is not None:
        a, b = _pct_change(iwm, 20), _pct_change(spy, 20)
        if a is not None and b is not None:
            snap["breadth_iwm_vs_spy_20d"] = a - b
    if spy is not None and qqq is not None:
        a, b = _pct_change(qqq, 20), _pct_change(spy, 20)
        if a is not None and b is not None:
            snap["qqq_vs_spy_20d"] = a - b
    if tnx is not None and len(tnx) > 5:
        snap["tnx_chg_5d_bp"] = (float(tnx.iloc[-1]) - float(tnx.iloc[-6])) * 10.0

    snap["session"] = get_session_phase()
    snap["regime"], snap["regime_label"] = classify_regime(snap)

    _CACHE["snapshot"] = (datetime.datetime.now(), snap)
    return snap


REGIME_LABELS = {
    "STRESS": "Vol-Stress — Korrelationen brechen, Gaps über Stops",
    "TREND_UP": "Sauberer Aufwärtstrend — Momentum trägt",
    "TREND_DOWN": "Sauberer Abwärtstrend — Long-Only-Momentum unbrauchbar",
    "LOW_VOL_RANGE": "Ruhige Range — ideal für Spread-/Mean-Reversion",
    "CHOP": "Richtungslos mit Vol — Ausbrüche verpuffen",
    "UNKNOWN": "Datenlage unzureichend",
}


def classify_regime(snap: Dict[str, Any]) -> tuple:
    """Übersetzt den Snapshot in ein Regime-Label."""
    vix = snap.get("vix")
    vix_chg = snap.get("vix_chg_5d_pct")
    er = snap.get("efficiency_ratio")
    rv = snap.get("realized_vol_20d")
    last, sma50 = snap.get("spy_last"), snap.get("spy_sma50")

    if vix is None or er is None:
        return "UNKNOWN", REGIME_LABELS["UNKNOWN"]

    if vix >= 30 or (vix_chg is not None and vix_chg >= 40.0):
        return "STRESS", REGIME_LABELS["STRESS"]

    trending = er >= 0.35
    up = last is not None and sma50 is not None and last >= sma50

    if trending and up:
        return "TREND_UP", REGIME_LABELS["TREND_UP"]
    if trending and not up:
        return "TREND_DOWN", REGIME_LABELS["TREND_DOWN"]
    if rv is not None and rv < 13.0 and er < 0.25:
        return "LOW_VOL_RANGE", REGIME_LABELS["LOW_VOL_RANGE"]
    return "CHOP", REGIME_LABELS["CHOP"]


# ==========================================================================
# Portfolio-Kontext
# ==========================================================================

def fetch_portfolio_context() -> Dict[str, Any]:
    """Depot-Kennzahlen für Exposure-Gates. Degradiert sauber ohne Alpaca."""
    ctx: Dict[str, Any] = {
        "alpaca": is_alpaca_configured(),
        "equity": None,
        "positions": [],
        "position_count": 0,
        "gross_exposure_pct": None,
        "net_exposure_pct": None,
        "top_weight_pct": None,
        "symbols": set(),
        "error": None,
    }
    if not ctx["alpaca"]:
        ctx["equity"] = 100_000.0  # Demo-Equity, identisch zu execute_signal
        return ctx

    try:
        acc = get_account_info() or {}
        ctx["equity"] = float(acc.get("equity", 0.0)) or None
        positions = get_positions() or []
        ctx["positions"] = positions
        ctx["position_count"] = len(positions)

        gross = net = 0.0
        top = 0.0
        for p in positions:
            try:
                mv = float(p.get("market_value", 0.0))
            except (TypeError, ValueError):
                mv = 0.0
            gross += abs(mv)
            net += mv
            top = max(top, abs(mv))
            sym = str(p.get("symbol", "")).upper()
            if sym:
                # Optionslegs (OSI) auf den Basiswert zurückführen
                ctx["symbols"].add(re.match(r"^([A-Z]+)", sym).group(1) if re.match(r"^([A-Z]+)", sym) else sym)

        if ctx["equity"]:
            ctx["gross_exposure_pct"] = gross / ctx["equity"] * 100.0
            ctx["net_exposure_pct"] = net / ctx["equity"] * 100.0
            ctx["top_weight_pct"] = top / ctx["equity"] * 100.0
    except Exception as e:
        ctx["error"] = str(e)
    return ctx


def read_falcone_activity(lookback_minutes: int = 240) -> Dict[str, Any]:
    """
    Liest falcone_engine.log und liefert die jüngste Signal-/Order-Historie.
    Grundlage für Cooldown- und Doppelsignal-Checks.
    """
    out = {"last_execution_per_ticker": {}, "executions_today": 0, "last_scan": None, "log_exists": False}
    if not os.path.exists(FALCONE_LOG):
        return out
    out["log_exists"] = True
    now = datetime.datetime.now()
    today = now.date()
    try:
        with open(FALCONE_LOG, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-2000:]
    except Exception:
        return out

    for line in lines:
        m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$", line.strip())
        if not m:
            continue
        try:
            ts = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        body = m.group(2)

        if "scan_markets" in body:
            out["last_scan"] = ts
        if "execute_signal" in body:
            if ts.date() == today:
                out["executions_today"] += 1
            tm = re.search(r"\b(?:contract\(s\)|shares eq\))\s+([A-Z]{1,6})\b", body) or \
                 re.search(r"\b([A-Z]{2,6})\s+@\s+\$", body)
            if tm:
                tk = tm.group(1)
                prev = out["last_execution_per_ticker"].get(tk)
                if prev is None or ts > prev:
                    out["last_execution_per_ticker"][tk] = ts
    return out


# ==========================================================================
# Gates & Verdicts
# ==========================================================================

@dataclass
class Gate:
    name: str
    passed: bool
    detail: str
    hard: bool = True   # hard=True -> K.o., hard=False -> Warnung/Abzug


@dataclass
class AlgoVerdict:
    key: str
    name: str
    module: str
    purpose: str
    status: str = "BLOCKED"          # GO | CONDITIONAL | BLOCKED
    score: float = 0.0
    gates: List[Gate] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    mode_hint: Optional[str] = None
    entrypoint: str = ""

    @property
    def blocking_gates(self) -> List[Gate]:
        return [g for g in self.gates if g.hard and not g.passed]

    @property
    def warnings(self) -> List[Gate]:
        return [g for g in self.gates if not g.hard and not g.passed]

    def finalize(self) -> "AlgoVerdict":
        if self.blocking_gates:
            self.status = "BLOCKED"
            self.score = 0.0
        else:
            self.score = float(max(0.0, min(100.0, self.score)))
            self.status = "GO" if (self.score >= 55.0 and not self.warnings) else "CONDITIONAL"
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["blocking_gates"] = [asdict(g) for g in self.blocking_gates]
        d["warnings"] = [asdict(g) for g in self.warnings]
        return d


def _eval_falcone(snap: Dict[str, Any], pf: Dict[str, Any], act: Dict[str, Any]) -> AlgoVerdict:
    """
    Falcone-Engine: Long-Only Intraday-Momentum auf 5m-Bars, zwei Trigger-Zweige
    (Volumen-Spike und VPEI-Mid-Day-Drift), Ausführung als Synthetic Swap.
    """
    v = AlgoVerdict(
        key="FALCONE_VPEI",
        name="Falcone Engine (VPEI / Volumen-Spike)",
        module="falcone_server.py",
        purpose="Intraday-Momentum long-only auf 5m-Bars, Ausführung via Synthetic Swap",
        entrypoint="falcone_server.scan_signals() → preflight → execute_signal()",
    )
    sess = snap["session"]
    phase = sess["phase"]
    vix = snap.get("vix")
    er = snap.get("efficiency_ratio")
    regime = snap.get("regime")

    # --- HARD GATES ---
    v.gates.append(Gate(
        "Kassa-Session offen", sess["cash_session_open"],
        f"Phase: {sess['label']} — die Engine liest die letzte geschlossene 5m-Kerze; "
        f"außerhalb der Session wiederholt sie ein totes Signal.", hard=True))
    v.gates.append(Gate(
        "VIX < 35", vix is not None and vix < 35.0,
        f"VIX {vix:.1f}" if vix is not None else "VIX unbekannt",
        hard=True))
    v.gates.append(Gate(
        "Regime nicht TREND_DOWN/STRESS", regime not in ("TREND_DOWN", "STRESS"),
        f"Regime {regime}: Die Engine kennt nur Long-Signale (is_bullish), "
        f"im Abwärtstrend systematisch gegen den Markt.", hard=True))
    v.gates.append(Gate(
        "Tages-Ordervolumen < 8", act.get("executions_today", 0) < 8,
        f"{act.get('executions_today', 0)} Ausführungen heute geloggt", hard=True))

    # --- SCORE ---
    if phase in ("OPEN_DRIVE", "POWER_HOUR"):
        v.score += 35
        v.mode_hint = "VOLUME_SPIKE"
        v.reasons.append("Opening Drive / Power Hour: Volumen-Spike-Zweig ist hier trennscharf (+35).")
    elif phase == "MIDDAY":
        v.score += 22
        v.mode_hint = "VPEI_DRIFT"
        v.reasons.append("Midday-Lull: nur der VPEI-Drift-Zweig (Vol < 1.5×μ) ist sinnvoll (+22).")
    else:
        v.reasons.append("Außerhalb der Kassa-Session kein valider Bar-Kontext (+0).")

    if er is not None:
        if er >= 0.35:
            v.score += 25
            v.reasons.append(f"Efficiency Ratio {er:.2f} ≥ 0.35 — Ausbrüche laufen (+25).")
        elif er >= 0.22:
            v.score += 10
            v.reasons.append(f"Efficiency Ratio {er:.2f} — gemischt (+10).")
        else:
            v.score -= 10
            v.reasons.append(f"Efficiency Ratio {er:.2f} < 0.22 — Ausbrüche verpuffen (−10).")

    if vix is not None:
        if 12.0 <= vix <= 26.0:
            v.score += 20
            v.reasons.append(f"VIX {vix:.1f} im Arbeitsbereich 12–26 (+20).")
        elif vix < 12.0:
            v.score += 5
            v.reasons.append(f"VIX {vix:.1f} sehr niedrig — wenig Bewegung je Spike (+5).")
        else:
            v.score -= 5
            v.reasons.append(f"VIX {vix:.1f} erhöht — Stops werden übersprungen (−5).")

    if regime == "TREND_UP":
        v.score += 15
        v.reasons.append("Regime TREND_UP passt zur Long-Only-Ausrichtung (+15).")
    elif regime == "CHOP":
        v.score -= 5
        v.reasons.append("Regime CHOP — erhöhte Fehlausbruchsquote (−5).")

    # --- WEICHE GATES ---
    v.gates.append(Gate(
        "Alpaca konfiguriert", bool(pf.get("alpaca")),
        "Ohne Alpaca läuft execute_signal im SIM-Modus (keine echte Order).", hard=False))
    gross = pf.get("gross_exposure_pct")
    v.gates.append(Gate(
        "Bruttoexposure < 150%", gross is None or gross < MAX_GROSS_EXPOSURE_PCT * 100,
        f"Bruttoexposure {gross:.0f}%" if gross is not None else "unbekannt", hard=False))
    return v.finalize()


def _eval_stat_arb(snap: Dict[str, Any], pf: Dict[str, Any], act: Dict[str, Any]) -> AlgoVerdict:
    v = AlgoVerdict(
        key="STAT_ARB_PAIRS",
        name="Statistical Arbitrage (Pairs)",
        module="arbitrage_lab.py / pairs_tracker.py",
        purpose="Marktneutrale Spread-Mean-Reversion auf kointegrierten Paaren",
        entrypoint="StatisticalArbitrageLab.calculate_pair_suitability() → register_pair()",
    )
    vix = snap.get("vix")
    vix_chg = snap.get("vix_chg_5d_pct")
    er = snap.get("efficiency_ratio")
    regime = snap.get("regime")
    sess = snap["session"]

    v.gates.append(Gate(
        "Kein Korrelationsbruch", not (vix_chg is not None and vix_chg >= 40.0),
        f"VIX 5T {vix_chg:+.0f}%" if vix_chg is not None else "unbekannt",
        hard=True))
    v.gates.append(Gate(
        "VIX < 32", vix is not None and vix < 32.0,
        f"VIX {vix:.1f} — im Stress divergieren Spreads statt zu konvergieren"
        if vix is not None else "VIX unbekannt", hard=True))

    if regime in ("LOW_VOL_RANGE", "CHOP"):
        v.score += 40
        v.reasons.append(f"Regime {regime} — Spread-Rückkehr ist hier das dominante Verhalten (+40).")
    elif regime == "TREND_UP":
        v.score += 12
        v.reasons.append("Trendregime — Paare driften auseinander, kleinere Sizing-Empfehlung (+12).")

    if er is not None and er < 0.25:
        v.score += 25
        v.reasons.append(f"Efficiency Ratio {er:.2f} < 0.25 — Sägezahnmarkt (+25).")
    elif er is not None and er >= 0.45:
        v.score -= 10
        v.reasons.append(f"Efficiency Ratio {er:.2f} — starker Trend belastet Spreads (−10).")

    if vix is not None and vix < 22.0:
        v.score += 20
        v.reasons.append(f"VIX {vix:.1f} < 22 — stabile Korrelationsstruktur (+20).")

    # Anders als die Falcone-Engine braucht Stat-Arb keine Live-Bars
    if not sess["cash_session_open"]:
        v.score += 5
        v.reasons.append("Analyse/Screening ist auch außerhalb der Session möglich (+5).")
    else:
        v.score += 10
        v.reasons.append("Session offen — Legs können sofort gepaart ausgeführt werden (+10).")

    v.gates.append(Gate(
        "Session offen für Execution", sess["cash_session_open"],
        "Außerhalb der Session nur Screening, kein Legging (Leg-Risiko).", hard=False))
    return v.finalize()


def _eval_premarket(snap: Dict[str, Any], pf: Dict[str, Any], act: Dict[str, Any]) -> AlgoVerdict:
    v = AlgoVerdict(
        key="PREMARKET_VOLRATE",
        name="Premarket Volume-Rate Scan",
        module="premarket_scan.py",
        purpose="Volumen-pro-Minute-Ranking im Premarket + Stat-Arb-Gegenseite",
        entrypoint="premarket_scan.volume_rate_scan() → build_pair()",
    )
    sess = snap["session"]
    phase = sess["phase"]

    v.gates.append(Gate(
        "Premarket-Fenster (04:00–09:30 ET)", phase == "PRE",
        f"Phase: {sess['label']} — der Scan liest ausschließlich Premarket-Bars.", hard=True))

    if phase == "PRE":
        v.score += 70
        v.reasons.append("Premarket aktiv — einziges Zeitfenster, in dem der Scan Daten hat (+70).")
        vix = snap.get("vix")
        if vix is not None and vix >= 18.0:
            v.score += 15
            v.reasons.append(f"VIX {vix:.1f} — erhöhte Premarket-Aktivität, mehr Kandidaten (+15).")
        else:
            v.score += 5
            v.reasons.append("Ruhiges Premarket — wenige echte Rate-Ausreißer (+5).")
    return v.finalize()


def _eval_execution(snap: Dict[str, Any], pf: Dict[str, Any], act: Dict[str, Any]) -> AlgoVerdict:
    v = AlgoVerdict(
        key="EXEC_TWAP_VWAP",
        name="TWAP / VWAP Execution",
        module="execution_algo.py",
        purpose="Impact-Minimierung beim Auf-/Abbau großer Positionen (kein Alpha)",
        entrypoint="ExecutionAlgoManager.execute_algo_trade()",
    )
    sess = snap["session"]
    rv = snap.get("realized_vol_20d")
    vix = snap.get("vix")

    v.gates.append(Gate(
        "Kassa-Session offen", sess["cash_session_open"],
        f"Phase: {sess['label']} — Slices brauchen Liquidität.", hard=True))
    v.gates.append(Gate(
        "Alpaca konfiguriert", bool(pf.get("alpaca")),
        "Ohne Broker-Anbindung keine Slice-Ausführung.", hard=True))
    mtc = sess.get("minutes_to_close")
    v.gates.append(Gate(
        "Genug Restzeit bis Close", (mtc or 0) >= 20,
        f"{mtc} Min. bis Close — Schedule muss durchlaufen." if mtc is not None
        else "Session geschlossen — kein Schedule-Fenster.", hard=True))

    v.score += 45
    v.reasons.append("Execution-Layer ist regime-unabhängig einsetzbar (+45).")
    if vix is not None and vix >= 22.0:
        v.score += 20
        v.reasons.append(f"VIX {vix:.1f} — Scheibchenweise Ausführung senkt Impact spürbar (+20).")
    if rv is not None and rv >= 18.0:
        v.score += 10
        v.reasons.append(f"Realized Vol {rv:.0f}% — VWAP dem Market-Order vorziehen (+10).")
    if sess["phase"] == "MIDDAY":
        v.score += 10
        v.reasons.append("Midday: dünnes Buch, TWAP schont den Spread (+10).")
    return v.finalize()


def _eval_hedge(snap: Dict[str, Any], pf: Dict[str, Any], act: Dict[str, Any]) -> AlgoVerdict:
    v = AlgoVerdict(
        key="MARKET_HEDGE",
        name="Market Hedge (Protective Put / Synthetic Short)",
        module="market_hedger.py",
        purpose="Absicherung von Netto-Long-Exposure statt neuer Richtungswette",
        entrypoint="MarketHedger.execute_protective_put() / execute_synthetic_short()",
    )
    sess = snap["session"]
    vix = snap.get("vix")
    vix_chg = snap.get("vix_chg_5d_pct")
    regime = snap.get("regime")
    net = pf.get("net_exposure_pct")

    v.gates.append(Gate(
        "Kassa-Session offen", sess["cash_session_open"],
        f"Phase: {sess['label']} — Optionslegs brauchen handelbare Quotes.", hard=True))
    v.gates.append(Gate(
        "Netto-Long-Exposure vorhanden", net is None or net > 5.0,
        f"Netto-Exposure {net:.0f}%" if net is not None else "unbekannt (Demo-Depot)",
        hard=True))

    if regime == "STRESS":
        v.score += 45
        v.reasons.append("Stress-Regime — Absicherung schlägt Neupositionierung (+45).")
    if regime == "TREND_DOWN":
        v.score += 30
        v.reasons.append("Abwärtstrend — Long-Only-Alpha ist gesperrt, Hedge bleibt (+30).")
    if vix_chg is not None and vix_chg >= 25.0:
        v.score += 20
        v.reasons.append(f"VIX +{vix_chg:.0f}% in 5T — Vol-Schock im Anlauf (+20).")
    if net is not None and net >= 80.0:
        v.score += 20
        v.reasons.append(f"Netto-Long {net:.0f}% — hohe Direktionalität (+20).")
    if vix is not None and vix >= 28.0:
        v.reasons.append(f"VIX {vix:.1f}: Put-Prämien bereits teuer, Synthetic Short prüfen.")
        v.gates.append(Gate("Put-Prämien nicht überteuert", vix < 28.0,
                            f"VIX {vix:.1f} ≥ 28 — Protective Put teuer erkauft.", hard=False))
    if snap.get("spy_dist_sma50_pct") is not None and snap["spy_dist_sma50_pct"] < -2.0:
        v.score += 10
        v.reasons.append(f"SPY {snap['spy_dist_sma50_pct']:.1f}% unter SMA50 (+10).")
    return v.finalize()


_EVALUATORS = [_eval_falcone, _eval_stat_arb, _eval_premarket, _eval_execution, _eval_hedge]


def route(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Hauptfunktion: liefert Regime, Depot-Kontext und die gerankte Algo-Empfehlung.
    Führt selbst keine Orders aus.
    """
    snap = fetch_regime_snapshot(force=force_refresh)
    pf = fetch_portfolio_context()
    act = read_falcone_activity()

    verdicts = [ev(snap, pf, act) for ev in _EVALUATORS]
    verdicts.sort(key=lambda v: (v.status != "GO", v.status != "CONDITIONAL", -v.score))

    live = [v for v in verdicts if v.status in ("GO", "CONDITIONAL")]
    recommendation = live[0] if live else None

    return {
        "timestamp": snap["timestamp"],
        "snapshot": snap,
        "portfolio": pf,
        "activity": act,
        "verdicts": verdicts,
        "recommendation": recommendation,
        "stand_down": recommendation is None,
    }


# ==========================================================================
# Preflight — Signal-Ebene
# ==========================================================================

@dataclass
class PreflightResult:
    ticker: str
    verdict: str                     # PASS | WARN | BLOCK
    checks: List[Gate] = field(default_factory=list)
    suggested_contracts: int = 0
    notional: float = 0.0
    notional_pct: float = 0.0
    implied_risk_pct: float = 0.0
    note: str = ""


def _category_for(ticker: str) -> str:
    try:
        from falcone_server import NASDAQ_TICKERS
        return "NASDAQ" if ticker.upper() in NASDAQ_TICKERS else "RUSSELL"
    except Exception:
        return "RUSSELL"


def preflight_signal(signal: Dict[str, Any], equity: float,
                     pf: Optional[Dict[str, Any]] = None,
                     act: Optional[Dict[str, Any]] = None) -> PreflightResult:
    """
    Prüft ein einzelnes Falcone-Signal gegen die Ausführungs-Realität.

    Der wichtigste Check ist die Positionsgrößen-Kohärenz: execute_signal rechnet
    das risikobasierte Stückvolumen in Optionskontrakte um (qty/100) und erzwingt
    mindestens 1 Kontrakt. Bei teuren Basiswerten reißt dieser Mindestkontrakt die
    15%-Kappe — hier wird das sichtbar gemacht, bevor die Order läuft.
    """
    pf = pf or {}
    act = act or {}
    ticker = str(signal.get("ticker", "")).upper()
    price = float(signal.get("close", 0.0) or 0.0)
    sl = float(signal.get("sl", 0.0) or 0.0)
    tp = float(signal.get("tp", 0.0) or 0.0)
    res = PreflightResult(ticker=ticker, verdict="PASS")

    # 1) Bar-Frische
    age = signal.get("bar_age_min")
    res.checks.append(Gate(
        "Bar-Frische", age is not None and age <= MAX_BAR_AGE_MIN,
        f"Signal-Kerze {age:.1f} Min. alt (Limit {MAX_BAR_AGE_MIN:.0f})"
        if age is not None else "Bar-Zeitstempel fehlt", hard=True))

    # 2) Liquidität
    dollar_vol = signal.get("dollar_volume")
    if dollar_vol is None:
        dollar_vol = price * float(signal.get("volume", 0) or 0)
    res.checks.append(Gate(
        "Kerzen-Umsatz ≥ 250k USD", dollar_vol >= MIN_BAR_DOLLAR_VOLUME,
        f"{dollar_vol:,.0f} USD in der Signal-Kerze", hard=True))
    res.checks.append(Gate(
        "Kurs ≥ 5 USD", price >= MIN_PRICE, f"Kurs ${price:.2f}", hard=True))

    # 3) Risiko/Ertrag & Stop-Plausibilität
    stop_dist = abs(price - sl)
    stop_pct = (stop_dist / price * 100.0) if price else 0.0
    rr = ((tp - price) / stop_dist) if stop_dist > 0 else 0.0
    res.checks.append(Gate(
        "RR ≥ 1.8", rr >= MIN_RR, f"RR {rr:.2f} (TP ${tp:.2f} / SL ${sl:.2f})", hard=True))
    res.checks.append(Gate(
        "Stop-Distanz 0.3–8%", MIN_STOP_PCT <= stop_pct <= MAX_STOP_PCT,
        f"Stop {stop_pct:.2f}% vom Kurs", hard=True))

    # 4) Positionsgröße / Kappen-Kohärenz
    category = _category_for(ticker)
    risk_pct = RISK_PCT_NASDAQ if category == "NASDAQ" else RISK_PCT_RUSSELL
    eff_stop = stop_dist if stop_dist > 0.01 else price * 0.02
    raw_qty = (equity * risk_pct) / eff_stop if eff_stop else 0.0
    max_position_value = equity * MAX_POSITION_PCT
    capped_qty = max_position_value / price if price else 0.0
    shares = min(raw_qty, capped_qty)
    max_contracts_by_cap = int(math.floor(max_position_value / (CONTRACT_MULTIPLIER * price))) if price else 0
    contracts = max(1, min(int(round(shares / CONTRACT_MULTIPLIER)), max(max_contracts_by_cap, 1)))

    res.suggested_contracts = contracts
    res.notional = contracts * CONTRACT_MULTIPLIER * price
    res.notional_pct = (res.notional / equity * 100.0) if equity else 0.0
    res.implied_risk_pct = (contracts * CONTRACT_MULTIPLIER * eff_stop / equity * 100.0) if equity else 0.0

    cap_ok = max_contracts_by_cap >= 1
    cap_detail = (
        f"{contracts} Kontrakt(e) = ${res.notional:,.0f} = {res.notional_pct:.1f}% des Depots "
        f"(risikobasiert waeren {shares:.0f} Aktien)"
        if cap_ok else
        f"1 Mindestkontrakt = ${res.notional:,.0f} = {res.notional_pct:.1f}% des Depots — "
        f"Basiswert bei ${price:.2f} zu teuer fuer die 15%-Kappe, execute_signal lehnt ab"
    )
    res.checks.append(Gate("Notional ≤ 15% Equity", cap_ok, cap_detail, hard=True))
    res.checks.append(Gate(
        f"Implizites Risiko ≤ {risk_pct*200:.1f}%", res.implied_risk_pct <= risk_pct * 200.0,
        f"{res.implied_risk_pct:.2f}% des Depots bei Stop-Auslösung "
        f"(Ziel {risk_pct*100:.1f}%, Kategorie {category})", hard=False))

    # 5) Cooldown & bestehende Exposure
    last_exec = (act.get("last_execution_per_ticker") or {}).get(ticker)
    cooled = True
    detail = "kein vorheriges Signal geloggt"
    if last_exec:
        mins = (datetime.datetime.now() - last_exec).total_seconds() / 60.0
        cooled = mins >= COOLDOWN_MINUTES
        detail = f"letzte Ausführung vor {mins:.0f} Min. (Cooldown {COOLDOWN_MINUTES} Min.)"
    res.checks.append(Gate("Cooldown eingehalten", cooled, detail, hard=True))

    held = ticker in (pf.get("symbols") or set())
    res.checks.append(Gate("Keine bestehende Position", not held,
                           f"{ticker} bereits im Depot" if held else "kein Bestand", hard=False))

    hard_fail = [c for c in res.checks if c.hard and not c.passed]
    soft_fail = [c for c in res.checks if not c.hard and not c.passed]
    if hard_fail:
        res.verdict = "BLOCK"
        res.note = hard_fail[0].detail
    elif soft_fail:
        res.verdict = "WARN"
        res.note = soft_fail[0].detail
    else:
        res.note = f"{contracts} Kontrakt(e), {res.notional_pct:.1f}% Notional, RR {rr:.2f}"
    return res


def preflight_signals(signals: List[Dict[str, Any]],
                      equity: Optional[float] = None) -> List[PreflightResult]:
    """Preflight über eine komplette Signal-Liste aus falcone_server.scan_signals()."""
    pf = fetch_portfolio_context()
    act = read_falcone_activity()
    eq = equity or pf.get("equity") or 100_000.0
    return [preflight_signal(s, eq, pf, act) for s in signals]


# ==========================================================================
# CLI
# ==========================================================================

def _print_report(result: Dict[str, Any]) -> None:
    snap = result["snapshot"]
    print("=" * 78)
    print(f"ALGO ROUTER — {result['timestamp']}")
    print("=" * 78)
    print(f"Session : {snap['session']['label']}  ({snap['session']['ny_time']} ET)")
    print(f"Regime  : {snap['regime']} — {snap['regime_label']}")
    print(f"VIX     : {snap['vix']:.2f}" if snap.get("vix") else "VIX     : n/a", end="")
    if snap.get("vix_chg_5d_pct") is not None:
        print(f"  ({snap['vix_chg_5d_pct']:+.1f}% 5T)")
    else:
        print()
    if snap.get("efficiency_ratio") is not None:
        print(f"ER(20)  : {snap['efficiency_ratio']:.2f}", end="")
    if snap.get("realized_vol_20d") is not None:
        print(f"   RV(20): {snap['realized_vol_20d']:.1f}%", end="")
    print()
    pf = result["portfolio"]
    net = pf.get("net_exposure_pct")
    print(f"Depot   : Equity ${pf.get('equity') or 0:,.0f} | "
          f"{pf.get('position_count', 0)} Positionen | "
          f"Netto {f'{net:.0f}%' if net is not None else 'n/a'}")
    print("-" * 78)
    for v in result["verdicts"]:
        print(f"[{v.status:^11}] {v.score:5.1f}  {v.name}")
        for g in v.blocking_gates:
            print(f"              ✗ GESPERRT: {g.name} — {g.detail}")
        for g in v.warnings:
            print(f"              ! WARNUNG : {g.name} — {g.detail}")
        for r in v.reasons[:3]:
            print(f"              · {r}")
    print("-" * 78)
    rec = result["recommendation"]
    print(f"EMPFEHLUNG: {rec.name} ({rec.status}, Score {rec.score:.1f})"
          if rec else "EMPFEHLUNG: STAND DOWN — kein Algorithmus freigegeben.")
    if rec and rec.mode_hint:
        print(f"            Modus: {rec.mode_hint}")


if __name__ == "__main__":
    result = route(force_refresh=True)
    _print_report(result)

    if "--preflight" in sys.argv:
        try:
            from falcone_server import scan_signals
            print("\nScanne Universum für Preflight ...")
            sigs = scan_signals()
            if not sigs:
                print("Keine Signale — nichts zu prüfen.")
            for r in preflight_signals(sigs):
                print(f"\n[{r.verdict}] {r.ticker} — {r.note}")
                for c in r.checks:
                    mark = "OK " if c.passed else ("XX " if c.hard else "!! ")
                    print(f"    {mark}{c.name}: {c.detail}")
        except Exception as e:
            print(f"Preflight fehlgeschlagen: {e}")
