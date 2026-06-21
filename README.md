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
