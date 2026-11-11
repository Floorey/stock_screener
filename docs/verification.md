# Implementierungs- und Betriebsnachweis

Stand: 6. November 2026, Europe/Berlin. Ausgangscommit:
`d116decbaa7fd13889003dd3e810f5f35b37d1ad`. Arbeitsbranch:
`codex/paper-stability-market-stress`. Änderungen sind lokal, nicht gepusht.

## Ergebnis

Das Original läuft als lokaler Streamlit-User-Dienst hinter dem Caddy-LAN-Proxy.
Die 13 ursprünglichen Haupttabs sind erhalten; Marktstress ist der 14. Haupttab.
Die neue manuelle Handelsoberfläche ersetzt die unmittelbare Ausführung im
Alpaca-Tab. Bestehende Schnellorder-/Bot-Aufrufe besitzen keine Schreibfreigabe.

| Prüfung | Frisch beobachtetes Ergebnis |
|---|---|
| Vollständige Testsuite | 55 Tests bestanden, 0 Fehler, 0 übersprungen |
| PostgreSQL-Integration | echte lokale Datenbank: Deduplizierung, Revisionen einschließlich A→B→A, Abbruch/Wiederaufnahme und Vintage-As-of geprüft |
| Originalverträge | feste Scores, altes Watchlist-Format, CSV, Excel und PDF geprüft |
| Brokergrenze | Paper-only, unbekannte Hosts/Redirects abgelehnt; 401/403/429/Timeout bleiben Fehler |
| Orderjournal | Konto-/Vorschau-Bindung, Ablauf, parallele Bestätigung, unklare Antworten, Abgleich ohne Wiederholung geprüft |
| Orderfunktionen | Aktien, Einzeloption, native MLeg mit signiertem Nettolimit, reduzierender Schluss und externe Orderstornierung mit Test-Broker geprüft |
| Dashboard | Offline-Render ohne unhandled Exception; zusätzlicher Render mit echtem Konto/Analytics und ersetzten Yahoo-/Token-Tracker-Daten ohne unhandled Exception |
| Netzwerk | TLS-Zertifikat verifiziert; ohne Anmeldung 401, mit Anmeldung Health-Endpunkt 200 |
| Abhängigkeiten | 88 lokale direkte/transitive Paketversionen festgeschrieben; venv ohne globale Pakete; pip check erfolgreich |
| Dauerbetrieb | App-Service und 15-Minuten-Importtimer aktiviert; PostgreSQL und Caddy in eigenem Compose-Projekt |

Testdetails liegen lokal in `.runtime/test-results.log`. Tests verwenden für
Schreiboperationen ausschließlich Fixtures; keine Testorder wurde abgesendet.

## Verifizierte Daten und Kontoanbindung

- Paper-Konto mit Endung `25417430`: ACTIVE, 11 Positionen, 0 offene Orders,
  effektives und genehmigtes Optionslevel 3, Shorting aktiv, Handel nicht
  brokerseitig gesperrt. Zeitabhängige Beobachtung, keine dauerhafte Zusage.
- 21 ETFs: 56.648 Tagesbars und 245.290 reguläre Minutenbars, zusammen 301.938.
- Tagesbars: 4. Januar 2016 bis 5. November 2026. Abfrage ab 2007 ausgeführt;
  frühere Jahre wurden vom Anbieter leer zurückgeliefert und bleiben sichtbar.
- Minutenbars: 25. September bis 5. November 2026, letzte 30 geschlossene
  Sitzungen. Fehlende Minuten werden nicht aufgefüllt; auch Intervalle ohne
  zulässige Trades können ohne Anbieter-Bar bleiben.
- Kalender ab 2007 und Rohantworten sind persistiert; abgeschlossene
  Alpaca-Importaufträge sind ohne Fehler beendet. Historische SIP-Daten sind
  verfügbar, aktuelle SIP-Quotes liefern mit diesem Zugang 403.
- Aktuelle IEX- und Indicative-Quote-Endpunkte sind erreichbar; OPRA liefert
  403. Die Laufzeit nutzt ausdrücklich IEX/Indicative, historische SIP-Reihen
  bleiben davon getrennt. Die geprüften Quotes stammen vom letzten Handelstag
  und sind vor heutiger Öffnung für das Orderticket zu alt.

## Offene Abnahme und Grenzen

Nach der Rückmeldung des Betreibers ist der manuelle Paper-Desk jetzt mit
`ALPACA_TRADING_ENABLED=true` in der lokalen Laufzeitdatei freigegeben.
Vorschau/Bestätigung pro Order und die Sperre automatischer Wege bleiben.
Reale Einzel-/Options-/MLeg-
Übermittlung und Fills sind ohne konkret bestätigte Order nicht geprüft.
Alte Optionsquotes können die 120-Sekunden-Frischegrenze nicht
erfüllen; einzelne Orders bleiben bei solchen Daten gesperrt. Indicative
liefert veränderte Quotes, nicht generell 15 Minuten verzögerte Quotes;
frische Indicative-Quotes können auch ohne OPRA genutzt werden. Native MLegs
unterstützen hier einen Basiswert, einen Verfall und einheitlich Öffnen oder
Schließen. Konservative Deckungsprüfung ist keine Broker-Marginoptimierung.

FRED/ALFRED-Importer und Vintage-Auswertung sind implementiert und gegen
Fixtures sowie PostgreSQL geprüft; ein FRED-Schlüssel fehlt noch. Der aktive
Timer importiert deshalb nur Alpaca. Makro-Livedaten wurden nicht verifiziert.
Historische Preis-Verfügbarkeitszeiten sind unbekannt; die Datenbasis ist
noch kein vollständiger Point-in-time-Backtestdatensatz. Der ursprüngliche
Optionsrisikobereich meldet unvollständige Bewertung statt erfundener Greeks.

Das öffentliche lokale CA-Zertifikat muss auf weiteren LAN-Geräten durch den
Betreiber installiert werden; dies wurde nicht auf fremden Geräten durchgeführt.
Kein Live-Handel, keine gebuchten Datenpakete, kein prognostisches Regimemodell.

## Ergänzung: integrierte Optionsauswahl

Alpaca-Katalogsuche mit explizitem Verfallsfenster und vollständiger Pagination
implementiert; real lesend mit SPY geprüft: 2.802 handelbare Standardkontrakte
im 14-Tage-Fenster. Auswahl nach Verfall, Typ und Strike übernimmt den Kontrakt
direkt ins Einzel- oder Mehrbein-Ticket. Der ursprüngliche Options-Screener
kann Kontrakte ebenfalls übergeben. Neue Tests prüfen Pagination, Fehler,
Handoffs und echte Streamlit-Klickfolgen ohne Broker-Schreibzugriff.
