import streamlit as st
import os
import sys
import json

# Ensure parent directory is in path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Try importing mcp_server, handle missing dependencies (e.g. mcp package) gracefully
mcp_available = True
mcp_error_message = ""
try:
    import mcp_server
except Exception as e:
    mcp_available = False
    mcp_error_message = str(e)

def render_mcp_tab():
    st.markdown('<div class="wl-banner"><h2>🔌 Model Context Protocol (MCP) Server Hub</h2></div>', unsafe_allow_html=True)
    st.markdown("""
    Das **Model Context Protocol (MCP)** ist ein offener Standard, der es KI-Assistenten (wie Claude Desktop, Cursor, Antigravity oder Windsurf) 
    ermöglicht, sicher auf Ihre lokalen Tools und Daten zuzugreifen. 
    Hier können Sie die Tools Ihres lokalen MCP-Servers testen und die Konfigurationsprofile für Ihre KI-Clients kopieren.
    """)

    if not mcp_available:
        st.error("⚠️ **MCP-Server Module konnten nicht geladen werden.**")
        st.info(f"Details zum Ladefehler: `{mcp_error_message}`")
        st.markdown("""
        Dies passiert meist, wenn die erforderlichen Abhängigkeiten nicht in der aktuellen Python-Umgebung installiert sind (z. B. auf Streamlit Cloud).
        
        **Lokale Lösung:**
        Installieren Sie das `mcp`-Paket in Ihrem Terminal:
        ```bash
        pip install mcp
        ```
        
        **Für gehostete Umgebungen:**
        Wir haben `mcp>=0.1.0` in die `requirements.txt` eingetragen. Sobald der Cloud-Server neu startet, sollte dieses Modul funktionieren.
        """)
        return

    # Main layout split into Instructions and Interactive Tool Tester
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("⚙️ Integration & Konfiguration")
        
        # Expandable config instructions for Claude Desktop
        with st.expander("💬 Integration in Claude Desktop", expanded=True):
            st.write("Fügen Sie diesen Block in Ihre Claude Desktop Konfigurationsdatei ein:")
            
            # Detect paths
            python_path = os.path.join(os.path.dirname(__file__), ".venv", "Scripts", "python.exe")
            server_path = os.path.join(os.path.dirname(__file__), "mcp_server.py")
            
            # Normalize to forward slashes for JSON config safety
            python_path_json = python_path.replace("\\", "/")
            server_path_json = server_path.replace("\\", "/")
            
            config_json = {
                "mcpServers": {
                    "alpaca-screener": {
                        "command": python_path_json,
                        "args": [server_path_json]
                    }
                }
            }
            
            st.code(json.dumps(config_json, indent=2), language="json")
            
            # Config file location
            appdata = os.getenv("APPDATA", r"C:\Users\lukas\AppData\Roaming")
            claude_config_path = os.path.join(appdata, "Claude", "claude_desktop_config.json")
            st.markdown(f"**Konfigurationsdatei-Pfad:**")
            st.code(claude_config_path, language="text")
            st.markdown("<small><i>Tipp: Falls die Datei oder der Ordner nicht existiert, erstellen Sie diese einfach. Starten Sie Claude Desktop nach dem Speichern neu.</i></small>", unsafe_allow_html=True)

        # Expandable config instructions for Cursor / VS Code
        with st.expander("💻 Integration in Cursor IDE", expanded=False):
            st.markdown("""
            Um diesen Server in **Cursor** zu nutzen:
            1. Öffnen Sie die **Cursor-Einstellungen** (Zahnrad oben rechts oder `Ctrl + ,`).
            2. Gehen Sie zu **Features** -> **MCP**.
            3. Klicken Sie auf **+ Add New MCP Server**.
            4. Tragen Sie folgende Details ein:
               * **Name:** `Alpaca-Screener`
               * **Type:** `command`
               * **Command:**
            """)
            st.code(f'"{python_path_json}" "{server_path_json}"', language="text")
            st.markdown("""
            5. Klicken Sie auf **Save**. Der Status sollte auf `Connected` (grün) springen.
            """)

        # How to run standalone
        with st.expander("🏃 Standalone starten (Entwickler/Debugging)", expanded=False):
            st.write("Sie können den MCP-Server manuell in der Konsole starten, um Fehlermeldungen (Logs) zu prüfen:")
            st.code(f"cd {os.path.dirname(__file__)}\n.venv\\Scripts\\python mcp_server.py", language="powershell")
            st.write("Der Server startet standardmäßig im **STDIO-Modus** und wartet auf Eingaben des Clients.")

    with col_right:
        st.subheader("🧪 Interaktiver Tool-Tester")
        st.write("Testen Sie die registrierten MCP-Tools direkt im Browser. Diese Funktionen werden aufgerufen, wenn die KI eine Anfrage stellt.")

        # Tool selection
        selected_tool = st.selectbox(
            "Wählen Sie ein MCP-Tool zum Testen:",
            [
                "get_watchlist (Watchlist abrufen)",
                "get_screener_scores (Aktuelle Screener-Scores abrufen)",
                "get_alpaca_account_summary (Alpaca Kontozusammenfassung)",
                "get_alpaca_portfolio_positions (Alpaca offene Positionen)",
                "execute_alpaca_trade (Order auf Alpaca ausführen)"
            ]
        )

        st.markdown("---")

        # Form for running tools
        if "get_watchlist" in selected_tool:
            st.markdown("**Tool:** `get_watchlist()`")
            st.markdown("*Beschreibung:* Gibt die Liste der Ticker-Symbole auf Ihrer Watchlist zurück.")
            
            if st.button("Tool ausführen", key="run_get_watchlist", use_container_width=True):
                with st.spinner("Rufe Watchlist ab..."):
                    try:
                        res = mcp_server.get_watchlist()
                        st.success("Ergebnis erfolgreich empfangen:")
                        st.json(res)
                    except Exception as e:
                        st.error(f"Fehler: {e}")

        elif "get_screener_scores" in selected_tool:
            st.markdown("**Tool:** `get_screener_scores()`")
            st.markdown("*Beschreibung:* Lädt die gecashten Screener-Daten und berechnet die aktuellen Long/Short-Scores. Hilft der KI, Trade-Kandidaten zu finden.")
            
            if st.button("Tool ausführen", key="run_screener_scores", use_container_width=True):
                with st.spinner("Berechne Scores aus Cache..."):
                    try:
                        res = mcp_server.get_screener_scores()
                        st.success("Ergebnis erfolgreich empfangen:")
                        st.text(res)
                    except Exception as e:
                        st.error(f"Fehler: {e}")

        elif "get_alpaca_account_summary" in selected_tool:
            st.markdown("**Tool:** `get_alpaca_account_summary()`")
            st.markdown("*Beschreibung:* Ruft Kontodaten wie Equity, Cash und Buying Power von Alpaca ab.")
            
            if st.button("Tool ausführen", key="run_account_summary", use_container_width=True):
                with st.spinner("Lade Alpaca-Kontodaten..."):
                    try:
                        res = mcp_server.get_alpaca_account_summary()
                        st.success("Ergebnis erfolgreich empfangen:")
                        st.text(res)
                    except Exception as e:
                        st.error(f"Fehler: {e}")

        elif "get_alpaca_portfolio_positions" in selected_tool:
            st.markdown("**Tool:** `get_alpaca_portfolio_positions()`")
            st.markdown("*Beschreibung:* Listet alle offenen Aktien- oder Optionspositionen im Alpaca-Konto auf.")
            
            if st.button("Tool ausführen", key="run_portfolio_positions", use_container_width=True):
                with st.spinner("Lade Portfolio-Positionen..."):
                    try:
                        res = mcp_server.get_alpaca_portfolio_positions()
                        st.success("Ergebnis erfolgreich empfangen:")
                        st.text(res)
                    except Exception as e:
                        st.error(f"Fehler: {e}")

        elif "execute_alpaca_trade" in selected_tool:
            st.markdown("**Tool:** `execute_alpaca_trade(...)`")
            st.markdown("*Beschreibung:* Platziert einen Kauf- oder Verkaufsauftrag über die Alpaca-API.")
            
            # Input fields for order
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                t_symbol = st.text_input("Ticker-Symbol (z.B. AAPL)", value="AAPL").upper().strip()
                t_qty = st.number_input("Menge / Shares", min_value=0.01, value=1.0, step=1.0)
            with col_t2:
                t_side = st.selectbox("Aktion", ["buy", "sell"])
                t_type = st.selectbox("Order-Typ", ["market", "limit"])
                
            t_limit_price = None
            if t_type == "limit":
                t_limit_price = st.number_input("Limit-Preis ($)", min_value=0.01, value=150.0, step=0.5)

            st.warning("⚠️ Achtung: Wenn Sie dieses Tool ausführen, wird eine reale Order (entsprechend Ihren Alpaca-Einstellungen, i.d.R. Paper Trading) platziert!")
            
            if st.button("🔥 Order über Tool ausführen", key="run_execute_trade", use_container_width=True):
                with st.spinner("Platziere Order über MCP..."):
                    try:
                        res = mcp_server.execute_alpaca_trade(
                            symbol=t_symbol,
                            qty=t_qty,
                            side=t_side,
                            order_type=t_type,
                            limit_price=t_limit_price
                        )
                        if "Fehler" in res:
                            st.error(res)
                        else:
                            st.success("Antwort vom MCP-Tool:")
                            st.write(res)
                    except Exception as e:
                        st.error(f"Fehler bei der Tool-Ausführung: {e}")
