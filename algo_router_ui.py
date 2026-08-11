"""
algo_router_ui.py — Bloomberg-Terminal-Screen für den Algo-Router (Kommando: ROUT).

Zeigt den analytischen Check: Regime-Snapshot, Freigabe/Sperre je Algorithmus
inklusive der ausschlaggebenden Gates, und den Preflight über konkrete
Falcone-Signale. Rendert nur — die gesamte Logik liegt in algo_router.py.

Ausführung wird hier bewusst nicht angeboten: der Screen entscheidet, WAS laufen
darf; das Abfeuern bleibt in den bestehenden Tabs (Strategie-Desk, Algo-Testlab)
bzw. in falcone_server.execute_signal.
"""

import re
import streamlit as st

from algo_router import route, preflight_signals, REGIME_LABELS

STATUS_STYLE = {
    "GO": ("bloomberg-green-text", "● FREIGEGEBEN"),
    "CONDITIONAL": ("bloomberg-amber-text", "◐ BEDINGT"),
    "BLOCKED": ("bloomberg-red-text", "○ GESPERRT"),
}


def _clean(html_str: str) -> str:
    """Streamlit-Markdown vertraegt keine Zeilenumbrueche in HTML-Bloecken."""
    return re.sub(r"\s+", " ", html_str.replace("\n", " ")).strip()


def _stat(label: str, value: str, color: str = "bloomberg-white-text", hint: str = "") -> str:
    hint_html = f"<br><span class='bloomberg-gray-text' style='font-size:0.72rem;'>{hint}</span>" if hint else ""
    return f"""
    <div class="bloomberg-stat-box" style="flex:1; min-width:150px; margin:4px;">
        <span class="bloomberg-gray-text" style="font-size:0.75rem;">{label}</span><br>
        <span class="{color}" style="font-size:1.25rem; font-weight:bold;">{value}</span>{hint_html}
    </div>
    """


def _fmt(val, spec: str = "{:.2f}", fallback: str = "N/A") -> str:
    try:
        return spec.format(val) if val is not None else fallback
    except (ValueError, TypeError):
        return fallback


def _render_regime(snap: dict, pf: dict) -> None:
    sess = snap["session"]
    regime = snap.get("regime", "UNKNOWN")

    regime_color = {
        "TREND_UP": "bloomberg-green-text",
        "LOW_VOL_RANGE": "bloomberg-cyan-text",
        "CHOP": "bloomberg-amber-text",
        "TREND_DOWN": "bloomberg-red-text",
        "STRESS": "bloomberg-red-text",
    }.get(regime, "bloomberg-gray-text")

    vix = snap.get("vix")
    vix_color = "bloomberg-green-text" if (vix is not None and vix < 20) else (
        "bloomberg-amber-text" if (vix is not None and vix < 28) else "bloomberg-red-text")
    er = snap.get("efficiency_ratio")
    er_color = "bloomberg-green-text" if (er is not None and er >= 0.35) else (
        "bloomberg-amber-text" if (er is not None and er >= 0.22) else "bloomberg-red-text")

    header = f"""
    <div style="background-color:#0c0c0c; border:1px solid #333; padding:10px; border-radius:4px;
                font-family:'Courier New', Courier, monospace; margin-bottom:12px;">
        <span style="color:#00ffff; font-weight:bold;">[1] MARKTREGIME &amp; SESSION-KONTEXT</span>
        <span class="bloomberg-gray-text" style="float:right;">STAND: {snap.get('timestamp', 'N/A')}</span>
    </div>
    """
    st.markdown(_clean(header), unsafe_allow_html=True)

    grid = "<div style='display:flex; flex-wrap:wrap;'>"
    grid += _stat("SESSION-PHASE", sess["phase"], "bloomberg-cyan-text", sess["label"])
    grid += _stat("REGIME", regime, regime_color, REGIME_LABELS.get(regime, ""))
    grid += _stat("VIX", _fmt(vix), vix_color,
                  f"5T {_fmt(snap.get('vix_chg_5d_pct'), '{:+.1f}%')} | "
                  f"1J-Perzentil {_fmt(snap.get('vix_pct_rank_1y'), '{:.0f}%')}")
    grid += _stat("EFFICIENCY RATIO", _fmt(er), er_color,
                  "&gt;0.35 Trend (Momentum) | &lt;0.25 Saegezahn (Stat-Arb)")
    grid += _stat("REALIZED VOL 20T", _fmt(snap.get("realized_vol_20d"), "{:.1f}%"),
                  "bloomberg-white-text", "annualisiert, SPY")
    grid += _stat("SPY vs SMA50", _fmt(snap.get("spy_dist_sma50_pct"), "{:+.2f}%"),
                  "bloomberg-green-text" if (snap.get("spy_dist_sma50_pct") or 0) >= 0 else "bloomberg-red-text",
                  "Richtungsfilter fuer Long-Only")
    grid += _stat("BREADTH IWM-SPY", _fmt(snap.get("breadth_iwm_vs_spy_20d"), "{:+.1f}%"),
                  "bloomberg-white-text", "20T relativ — Risikoappetit Small Caps")
    grid += _stat("US 10J", _fmt(snap.get("tnx"), "{:.2f}%"), "bloomberg-white-text",
                  f"5T {_fmt(snap.get('tnx_chg_5d_bp'), '{:+.0f} bp')}")
    grid += "</div>"
    st.markdown(_clean(grid), unsafe_allow_html=True)

    depot = "<div style='display:flex; flex-wrap:wrap; margin-top:6px;'>"
    depot += _stat("KONTO", "ALPACA LIVE/PAPER" if pf.get("alpaca") else "SIMULATION",
                   "bloomberg-green-text" if pf.get("alpaca") else "bloomberg-amber-text",
                   "" if pf.get("alpaca") else "Demo-Equity 100.000 USD")
    depot += _stat("EQUITY", f"${(pf.get('equity') or 0):,.0f}", "bloomberg-white-text",
                   f"{pf.get('position_count', 0)} Positionen")
    depot += _stat("NETTO-EXPOSURE", _fmt(pf.get("net_exposure_pct"), "{:.0f}%"),
                   "bloomberg-white-text", "Basis fuer den Hedge-Trigger")
    depot += _stat("BRUTTO-EXPOSURE", _fmt(pf.get("gross_exposure_pct"), "{:.0f}%"),
                   "bloomberg-white-text", "Limit 150%")
    depot += "</div>"
    st.markdown(_clean(depot), unsafe_allow_html=True)

    if not snap.get("data_ok"):
        st.warning("Marktdaten unvollstaendig (yfinance) — Regime-Klassifikation eingeschraenkt.", icon="⚠️")


def _render_verdicts(result: dict) -> None:
    header = """
    <div style="background-color:#0c0c0c; border:1px solid #333; padding:10px; border-radius:4px;
                font-family:'Courier New', Courier, monospace; margin:18px 0 12px 0;">
        <span style="color:#00ffff; font-weight:bold;">[2] ALGO-FREIGABE — TRIGGER-MATRIX</span>
    </div>
    """
    st.markdown(_clean(header), unsafe_allow_html=True)

    rec = result["recommendation"]
    if rec is None:
        st.markdown(_clean("""
        <div style="border:2px solid #ff3333; background-color:#110000; padding:14px; border-radius:4px;
                    font-family:'Courier New', Courier, monospace; text-align:center;">
            <span class="bloomberg-red-text" style="font-size:1.15rem; font-weight:bold;">
                STAND DOWN — KEIN ALGORITHMUS FREIGEGEBEN
            </span><br>
            <span class="bloomberg-gray-text">Alle Kandidaten scheitern an mindestens einem harten Gate.</span>
        </div>
        """), unsafe_allow_html=True)
    else:
        mode = f" | MODUS: {rec.mode_hint}" if rec.mode_hint else ""
        st.markdown(_clean(f"""
        <div style="border:2px solid #ffb300; background-color:#0d0a00; padding:14px; border-radius:4px;
                    font-family:'Courier New', Courier, monospace;">
            <span class="bloomberg-gray-text" style="font-size:0.8rem;">EMPFEHLUNG</span><br>
            <span class="bloomberg-amber-text" style="font-size:1.2rem; font-weight:bold;">{rec.name}</span>
            <span class="bloomberg-white-text"> — Score {rec.score:.0f}/100 | STATUS {rec.status}{mode}</span><br>
            <span class="bloomberg-gray-text" style="font-size:0.85rem;">Einstieg: {rec.entrypoint}</span>
        </div>
        """), unsafe_allow_html=True)

    rows = ""
    for v in result["verdicts"]:
        color, badge = STATUS_STYLE.get(v.status, ("bloomberg-gray-text", v.status))
        bar_w = int(max(0.0, min(100.0, v.score)))
        bar_col = "#00ff00" if v.status == "GO" else ("#ffb300" if v.status == "CONDITIONAL" else "#552222")
        blockers = "; ".join(g.name for g in v.blocking_gates) or "—"
        warns = "; ".join(g.name for g in v.warnings) or "—"
        rows += f"""
        <tr>
            <td class="bloomberg-cyan-text">{v.name}<br>
                <span class="bloomberg-gray-text" style="font-size:0.75rem;">{v.module}</span></td>
            <td class="{color}" style="white-space:nowrap;">{badge}</td>
            <td style="text-align:right;" class="bloomberg-white-text">{v.score:.0f}
                <div style="background:#1a1a1a; height:6px; width:100%; border-radius:3px; margin-top:3px;">
                    <div style="background:{bar_col}; height:6px; width:{bar_w}%; border-radius:3px;"></div>
                </div>
            </td>
            <td class="bloomberg-red-text" style="font-size:0.82rem;">{blockers}</td>
            <td class="bloomberg-amber-text" style="font-size:0.82rem;">{warns}</td>
        </tr>
        """

    table = f"""
    <table class="bloomberg-table" style="margin-top:12px;">
        <thead>
            <tr>
                <th style="text-align:left; width:30%;">ALGORITHMUS</th>
                <th style="text-align:left;">STATUS</th>
                <th style="text-align:right; width:16%;">SCORE</th>
                <th style="text-align:left;">HARTE SPERREN</th>
                <th style="text-align:left;">WARNUNGEN</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """
    st.markdown(_clean(table), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    for v in result["verdicts"]:
        color, badge = STATUS_STYLE.get(v.status, ("bloomberg-gray-text", v.status))
        with st.expander(f"{badge}  {v.name}  —  Score {v.score:.0f}"):
            st.markdown(f"**Zweck:** {v.purpose}")
            st.markdown(f"**Einstiegspunkt:** `{v.entrypoint}`")
            st.markdown("**Gates:**")
            for g in v.gates:
                if g.passed:
                    icon, tag = "✅", ""
                elif g.hard:
                    icon, tag = "⛔", " *(hart — sperrt)*"
                else:
                    icon, tag = "⚠️", " *(weich — Warnung)*"
                st.markdown(f"- {icon} **{g.name}**{tag}: {g.detail}")
            if v.reasons:
                st.markdown("**Score-Herleitung:**")
                for r in v.reasons:
                    st.markdown(f"- {r}")


def _render_preflight(result: dict) -> None:
    header = """
    <div style="background-color:#0c0c0c; border:1px solid #333; padding:10px; border-radius:4px;
                font-family:'Courier New', Courier, monospace; margin:18px 0 12px 0;">
        <span style="color:#00ffff; font-weight:bold;">[3] PREFLIGHT — SIGNALPRUEFUNG FALCONE ENGINE</span>
    </div>
    """
    st.markdown(_clean(header), unsafe_allow_html=True)

    falcone = next((v for v in result["verdicts"] if v.key == "FALCONE_VPEI"), None)
    if falcone and falcone.status == "BLOCKED":
        st.info(
            "Die Falcone-Engine ist im aktuellen Regime gesperrt — ein Scan ist trotzdem "
            "moeglich, die Signale sind dann rein informativ.", icon="ℹ️")

    col_a, col_b, col_c = st.columns([1.4, 1, 3])
    with col_a:
        run_scan = st.button("🔍 Scan + Preflight", key="rout_scan", use_container_width=True)
    with col_b:
        multiplier = st.number_input("Vol-Faktor", min_value=1.5, max_value=10.0,
                                     value=3.0, step=0.5, key="rout_mult",
                                     label_visibility="collapsed")
    with col_c:
        st.caption("Scannt Nasdaq-30 + Russell-30 und prueft jedes Signal auf Bar-Frische, "
                   "Liquiditaet, RR, Positionskappe und Cooldown. Es wird nichts ausgefuehrt.")

    if run_scan:
        with st.spinner("Falcone Engine scannt Universum ..."):
            try:
                from falcone_server import scan_signals
                signals = scan_signals(float(multiplier))
                st.session_state["rout_signals"] = signals
                st.session_state["rout_preflight"] = preflight_signals(signals)
            except Exception as e:
                st.error(f"Scan fehlgeschlagen: {e}")
                st.session_state["rout_signals"] = []
                st.session_state["rout_preflight"] = []

    results = st.session_state.get("rout_preflight")
    if results is None:
        st.markdown(_clean("<div class='bloomberg-gray-text' style=\"font-family:'Courier New', monospace;\">"
                           "NOCH KEIN SCAN AUSGEFUEHRT.</div>"), unsafe_allow_html=True)
        return
    if not results:
        st.markdown(_clean("<div class='bloomberg-red-text' style=\"font-family:'Courier New', monospace;\">"
                           "KEINE SIGNALE IM UNIVERSUM GEFUNDEN.</div>"), unsafe_allow_html=True)
        return

    signals = {s["ticker"]: s for s in st.session_state.get("rout_signals", [])}
    verdict_style = {
        "PASS": ("bloomberg-green-text", "● PASS"),
        "WARN": ("bloomberg-amber-text", "◐ WARN"),
        "BLOCK": ("bloomberg-red-text", "○ BLOCK"),
    }

    rows = ""
    for r in sorted(results, key=lambda x: {"PASS": 0, "WARN": 1, "BLOCK": 2}[x.verdict]):
        sig = signals.get(r.ticker, {})
        color, badge = verdict_style[r.verdict]
        rows += f"""
        <tr>
            <td class="bloomberg-cyan-text">{r.ticker}</td>
            <td class="bloomberg-gray-text">{sig.get('category', '—')}</td>
            <td class="bloomberg-white-text">{sig.get('trigger_type', '—')}</td>
            <td style="text-align:right;" class="bloomberg-white-text">${sig.get('close', 0.0):.2f}</td>
            <td style="text-align:right;" class="bloomberg-white-text">${sig.get('sl', 0.0):.2f}</td>
            <td style="text-align:right;" class="bloomberg-white-text">${sig.get('tp', 0.0):.2f}</td>
            <td style="text-align:right;" class="bloomberg-white-text">{r.suggested_contracts}</td>
            <td style="text-align:right;" class="bloomberg-white-text">{r.notional_pct:.1f}%</td>
            <td style="text-align:right;" class="bloomberg-white-text">{r.implied_risk_pct:.2f}%</td>
            <td class="{color}" style="white-space:nowrap;">{badge}</td>
            <td class="bloomberg-gray-text" style="font-size:0.8rem;">{r.note}</td>
        </tr>
        """

    table = f"""
    <table class="bloomberg-table" style="margin-top:12px;">
        <thead>
            <tr>
                <th style="text-align:left;">TICKER</th>
                <th style="text-align:left;">KAT.</th>
                <th style="text-align:left;">TRIGGER</th>
                <th style="text-align:right;">KURS</th>
                <th style="text-align:right;">STOP</th>
                <th style="text-align:right;">TARGET</th>
                <th style="text-align:right;">KONTR.</th>
                <th style="text-align:right;">NOTIONAL</th>
                <th style="text-align:right;">RISIKO</th>
                <th style="text-align:left;">PREFLIGHT</th>
                <th style="text-align:left;">BEFUND</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """
    st.markdown(_clean(table), unsafe_allow_html=True)

    n_pass = sum(1 for r in results if r.verdict == "PASS")
    n_warn = sum(1 for r in results if r.verdict == "WARN")
    n_block = sum(1 for r in results if r.verdict == "BLOCK")
    st.markdown(_clean(f"""
    <div style="font-family:'Courier New', monospace; margin-top:10px;">
        <span class="bloomberg-green-text">{n_pass} PASS</span> |
        <span class="bloomberg-amber-text">{n_warn} WARN</span> |
        <span class="bloomberg-red-text">{n_block} BLOCK</span>
        <span class="bloomberg-gray-text"> — von {len(results)} Rohsignalen</span>
    </div>
    """), unsafe_allow_html=True)

    for r in results:
        if r.verdict == "PASS":
            continue
        with st.expander(f"Details {r.ticker} — {r.verdict}"):
            for c in r.checks:
                icon = "✅" if c.passed else ("⛔" if c.hard else "⚠️")
                st.markdown(f"- {icon} **{c.name}**: {c.detail}")


def render_router_screen() -> None:
    """Einstiegspunkt fuer den ROUT-Screen im Bloomberg-Terminal-Tab."""
    st.markdown(
        "<h3 class='bloomberg-amber-text' style='margin-top:0;'>🧭 ROUT: ANALYTISCHER CHECK — "
        "WELCHER ALGORITHMUS DARF JETZT LAUFEN?</h3>", unsafe_allow_html=True)

    col_r, col_note = st.columns([1.4, 5])
    with col_r:
        refresh = st.button("♻️ Regime neu laden", key="rout_refresh", use_container_width=True)
    with col_note:
        st.caption("Der Router entscheidet ausschliesslich ueber Freigaben. Er platziert keine Orders — "
                   "die Ausfuehrung bleibt im Strategie-Desk bzw. in falcone_server.execute_signal.")

    with st.spinner("Regime-Snapshot wird berechnet ..."):
        try:
            result = route(force_refresh=bool(refresh))
        except Exception as e:
            st.error(f"Router-Fehler: {e}")
            return

    _render_regime(result["snapshot"], result["portfolio"])
    _render_verdicts(result)
    _render_preflight(result)
