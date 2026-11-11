# Fundamental Stock Screener & PDF Analyzer (Alpaca-kompatibel)

Dieses Tool hilft Ihnen dabei, fundamentale Daten von Aktien aus bekannten Indizes (S&P 500, Dow Jones, NASDAQ 100, Russell 2000) zu analysieren und zu bewerten. Es berechnet Long- und Short-Scores und prüft die direkte Handelbarkeit und Shortbarkeit über Alpaca. Zudem bietet es ein Modul zur automatischen Auswertung von PDF-Finanzberichten (z.B. 10-K/10-Q).

## Features

1. **Index Scraper:**
   - Lädt Ticker-Daten für **S&P 500**, **Dow Jones**, **NASDAQ 100** (über Wikipedia-Scraping) und **Russell 2000** (über GitHub-Listen).
2. **Alpaca Integration:**
   - Prüft über die Alpaca Assets API, welche Ticker **handelbar** (`tradable`), **leihbar** (`shortable`) und **leicht auszuleihen** (`easy_to_borrow`) sind.
3. **Fundamental Scoring Engine (yFinance):**
   - Lädt Finanzkennzahlen (KGV, KBV, Debt/Equity, Current Ratio, Cashflows, Margen, ROE, FCF) herunter.
   - Berechnet einen **Long-Score** (Unterbewertung & hohe Qualität) und einen **Short-Score** (Überbewertung, hohe Verschuldung & Cash-Burn).
4. **PDF Finanzbericht Analyzer:**
   - Uploader für PDF-Berichte im Streamlit Dashboard.
   - **Automatischer Scan** nach Zeilen mit wichtigen Finanzkennzahlen (Revenue, Net Income, Cash Flow, Debt).
   - **Keyword-Suche** zur schnellen Analyse von Risikofaktoren, Outlooks oder speziellen Begriffen mit Seitennummerierung und Kontext.
5. **Interaktives Streamlit Dashboard:**
   - Übersichtliche Visualisierung der Top-Kandidaten, Daten-Filterung, Excel/CSV-Export und Ticker-Einzelwertanalyse.

---

## Installation & Einrichtung

### 1. Projektordner betreten
Öffnen Sie Ihr Terminal (PowerShell) und navigieren Sie in das Projektverzeichnis:
```powershell
cd C:\Users\lukas\stock_screener
```

### 2. Abhängigkeiten installieren
Stellen Sie sicher, dass alle erforderlichen Pakete installiert sind (bereits im Setup durchgeführt):
```powershell
pip install -r requirements.txt
```

### 3. Alpaca Keys konfigurieren (Optional)
Öffnen Sie die `.env`-Datei im Projektverzeichnis und tragen Sie Ihre Alpaca-Schlüssel ein:
```env
ALPACA_API_KEY=IHR_ALPACA_KEY
ALPACA_SECRET_KEY=IHR_ALPACA_SECRET
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```
*Hinweis: Wenn Sie keine API-Schlüssel eintragen, nimmt das Tool standardmäßig an, dass alle Aktien handelbar und shortbar sind.*

---

## Ausführung

### A. Starten der Web-Anwendung (Streamlit Dashboard)
Führen Sie im Terminal folgenden Befehl aus, um das interaktive Dashboard im Browser zu öffnen:
```powershell
streamlit run app.py
```
Das Dashboard öffnet sich automatisch unter `http://localhost:8501`.

### B. Ausführen des CLI-Testskripts
Wenn Sie nur einen schnellen Test der fundamentalen Datengewinnung über die Konsole machen möchten:
```powershell
python screener.py
```
Dies lädt die ersten 15 Ticker des Dow Jones und gibt die Top-Kandidaten aus.

---

## Funktionsweise des Scoring-Modells

### Long-Score (Kauf-Kandidaten):
- KGV (P/E) zwischen 5 und 25 (+1)
- KBV (P/B) < 3.0 (+1)
- Verschuldungsgrad (Debt/Equity) < 1.0 (+1)
- Liquiditätsgrad (Current Ratio) > 1.5 (+1)
- Positiver Free Cash Flow (+1)
- ROE > 12% (+1)
- Umsatzwachstum YoY > 5% (+1)

### Short-Score (Leerverkauf-Kandidaten):
- Verschuldungsgrad (Debt/Equity) > 2.5 (+1)
- Liquiditätsgrad (Current Ratio) < 1.0 (+1)
- Negativer Free Cash Flow (+1)
- Unprofitabel & hohe Bewertung (KGV negativ & EV/Revenue > 12) (+1.5)
- KGV > 50 (+1)
- Umsatzwachstum YoY < -5% (+1)
- Nettomarge < -10% (+1)
- *Abzug:* Sehr hohe Short Interest (> 20%) verringert den Score leicht (-0.5), um das Risiko von Short Squeezes abzumildern.

---

## GitHub-Synchronisation

Dieses Verzeichnis ist bereits als lokales Git-Repository initialisiert. Um das Projekt auf GitHub zu veröffentlichen, führen Sie folgende Schritte in Ihrem Terminal aus:

1. **Erstellen Sie ein neues, leeres Repository** auf [github.com](https://github.com/new) (ohne README, .gitignore oder Lizenz).
2. **Kopieren Sie die Repository-URL** (z. B. `https://github.com/IhrNutzername/IhrRepoName.git`).
3. **Verbinden und pushen Sie** das Projekt über Ihr Terminal:
```powershell
git remote add origin https://github.com/IhrNutzername/IhrRepoName.git
git branch -M main
git push -u origin main
```
Lokale Änderungen an temporären Dateien (wie Cache, Watchlist und Exporte) sind über die Datei `.gitignore` bereits vom Commit ausgeschlossen, um sensible API-Schlüssel oder private Listen nicht öffentlich zu machen.


## Prognose-Reiter (Kronos / Timestral)

**Alpaca direkt** ist die Standardquelle: Ticker, Feed (IEX/SIP) und 1–20 Handelssitzungen wählen, dann **Daten laden**. Die Projekt-.env liefert ALPACA_API_KEY und ALPACA_SECRET_KEY ausschließlich serverseitig. 120 abgeschlossene Tageskerzen mit adjustment=all und Börsenkalender werden über den vorhandenen Alpaca-Leseclient abgerufen; Pagination wird vollständig verarbeitet, Wiederholungen und Lücken abgelehnt. Keine Datenbank und kein Modellserver zum Anzeigen der Kurse erforderlich.

**Prognose berechnen** nutzt genau die geladenen Daten für Kronos, Timestral oder beide. Keine erneute Kursabfrage; keine automatische Berechnung bei Reiter-/Parameterwechsel. Bei geändertem Ticker/Feed/Quelle/Horizont erneut Daten laden. Bei nicht erreichbarem Modell bleiben die Kurse sichtbar. P10–P90 ist ein nominales 80%-Band, nicht empirisch kalibriert. Keine automatische Orderausführung.

Die ausdrücklich auswählbare Quelle **Datenbank** liest den vorhandenen Analytics-Store. Keine stillen Quellenwechsel, keine automatische DB-Reparatur. Stand 11.11.2026: bestehender Kalender endet am 06.11.2026; diese Quelle meldet fehlende Zukunftssitzungen, bis der Kalender separat aktualisiert wurde. yfinance ist nicht Bestandteil dieses Prognose-Datenwegs.

Prognosedienst: serverseitige TIMELINE_BASE_URL, Standard http://127.0.0.1:8081. Bei getrennten Containern muss die Adresse aus Sicht des Screeners erreichbar sein. Kein frei eingebbarer API-Host im Browser. Modell-POST-Timeout: 5 s Verbindung / 120 s Lesen, keine automatischen Wiederholungen.

Dauerhafte separate Test-/Modellumgebung: `/home/lukasenderle/ChatGPT/stockscreener/.venv-forecast` (Python 3.12, CPU-PyTorch). Keine vorhandene .venv überschrieben. Lokaler Start des eigenständigen Timeline-Dienstes:

```bash
bash /home/lukasenderle/ChatGPT/stockscreener/tasks/run-timeline.sh
```

Screener mit derselben vollständigen Umgebung starten, sofern die bisherige Umgebung nicht zum Systeminterpreter passt:

```bash
/home/lukasenderle/ChatGPT/stockscreener/.venv-forecast/bin/python deploy/run.py app
```

Die Startbefehle richten keinen Boot-Autostart ein. Timeline benötigt gecachte Gewichte; HF_HUB_OFFLINE=1 verhindert Downloads. Exakte geprüfte Paketversionen und Tests: `/home/lukasenderle/ChatGPT/stockscreener/runs/direct-sources-20261111/`.

Tests: `python -m unittest discover -s tests -p 'test_*.py' -v`. Echte Abnahme: `/home/lukasenderle/ChatGPT/stockscreener/tasks/direct_sources_e2e.py`; sie nutzt echte Alpaca-Leseabfragen, die laufende DB nur lesend und den vorgesehenen Timeline-Dienst.
