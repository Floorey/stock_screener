# Original-Terminal: Betrieb und Abnahme

Ausgangsquelle: `https://github.com/Floorey/stock_screener`, Commit
`d116decbaa7fd13889003dd3e810f5f35b37d1ad`, Branch
`codex/paper-stability-market-stress`. Keine neue Frontend-Anwendung.

## Lokaler Aufbau

Python 3.14; `.venv` enthält die Projektabhängigkeiten lokal.
`requirements.lock.txt` hält die tatsächlich verwendeten 88 direkten und
transitiven Paketversionen für Python 3.14/Linux fest. Für einen anderen
Rechner eine eigene Umgebung verwenden:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
```

Das Serverkonto lädt Schlüssel aus `.env`; diese Datei nicht ins Repository
übernehmen und mit `chmod 600 .env` schützen:

```dotenv
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
FRED_API_KEY=...
```

Die Integration des Alpaca-Plugins in Codex stellt der Python-Anwendung keine
API-Schlüssel bereit. Schlüssel nicht in den Chat oder ein Browserformular eingeben.

## LAN-Zugang

Die einmalige Vorbereitung erzeugt zufällige lokale Passwörter; eine erneute
Ausführung überschreibt sie nicht:

```bash
.venv/bin/python deploy/prepare.py --lan-address 192.168.3.169
docker compose --env-file .runtime/runtime.env -f deploy/compose.yaml up -d --wait
.venv/bin/python deploy/run.py app
```

URL und Anmeldung stehen ausschließlich in `.runtime/access.txt`.
Streamlit bindet an `127.0.0.1:8501`, Caddy an die gewählte private Adresse,
HTTPS-Port 8443. PostgreSQL ist ausschließlich unter `127.0.0.1:15439` erreichbar.
REST/MCP-Server werden nicht gestartet. Keine Router-Portfreigabe einrichten.

```bash
docker cp blackgate-analytics-caddy-1:/data/caddy/pki/authorities/local/root.crt .runtime/blackgate-lan-ca.crt
```

Dieses **öffentliche CA-Zertifikat**, niemals den CA-Schlüssel, auf jedem
verwendeten Gerät als vertrauenswürdige lokale CA installieren. Dies muss auf
jedem Gerät durch dessen Betreiber erfolgen. Bei geänderter LAN-IP Caddyfile
bewusst anpassen und Proxy neu starten; keine öffentliche Adresse verwenden.

## Dauerbetrieb

Die mitgelieferten User-Units verwenden den aktuellen absoluten Projektpfad:

```bash
systemctl --user link "$PWD/deploy/blackgate-analytics-app.service"
systemctl --user link "$PWD/deploy/blackgate-analytics-import.service"
systemctl --user link "$PWD/deploy/blackgate-analytics-import.timer"
systemctl --user daemon-reload
systemctl --user enable --now blackgate-analytics-app.service
systemctl --user enable --now blackgate-analytics-import.timer
```

Der Importtimer läuft 15 Minuten nach Ende des vorherigen Laufs; überlappende
Timer-Aufrufe entstehen dadurch nicht. Fehlende Schlüssel bleiben ein Fehler,
kein erfolgreicher Import. Ein User-Service läuft nur bei verfügbarer
Benutzersitzung; Bootbetrieb ohne Anmeldung erfordert separat eingerichtetes
Linger. Dieser Aufbau verändert kein bestehendes Wayne-2-Deployment.

Der aktive Timer importiert zunächst nur Alpaca-SIP-Historie, da noch kein
FRED-Schlüssel vorliegt. Nach dessen Einrichtung zunächst explizit testen:

```bash
.venv/bin/python deploy/run.py import import --source fred
```

Danach kann in der Import-Service-Datei `--source alpaca` durch `--source all`
ersetzt und `systemctl --user daemon-reload` ausgeführt werden. SIP-Historie
und aktuelle IEX-Quotes sind absichtlich verschiedene, sichtbar benannte
Feeds: Der vorhandene Zugang erlaubt SIP-Historie, aber keine SIP-Echtzeitquotes.
OPRA ist ebenfalls nicht freigeschaltet. Indicative ist verfügbar und liefert
veränderte Quotes; die Trades dieses Feeds sind verzögert. Frische Indicative-
Quotes dürfen im manuellen Paper-Ticket verwendet werden; dieselbe
120-Sekunden-Frischeprüfung gilt wie bei anderen Quote-Feeds.
Der Import füllt fehlende Jahre, Minuten oder Berechtigungen nicht künstlich auf.

## Daten und Sicherungen

Analytics liegt im Docker-Volume `blackgate-analytics_analytics_pg`.
`docker compose down` erhält die Volumes; **kein `down -v`** verwenden.
Watchlist-/Cache-Dateien behalten ihr ursprüngliches Format; vor einer
Übernahme vorhandener lokaler Dateien Sicherung erstellen.
Das Orderjournal und `.runtime` müssen zusammen mit den bestehenden lokalen
Zustandsdateien gesichert werden. Journal nicht löschen, um unklare Orders
erneut abzusenden. Brokerkonto bleibt Autorität für Orders und Fills.

```bash
docker exec blackgate-analytics-postgres-1 pg_dump -U analytics -d analytics -Fc > .runtime/analytics-backup.dump
```

## Freigabe

`ALPACA_TRADING_ENABLED=false` ist die Ausgangseinstellung. Eine Verbindung
allein ist keine Handelsfreigabe. Kontoidentität, Datenberechtigungen,
Optionslevel und Vorschau-/Bestätigungspfad vor der Freigabe prüfen.
Paper-Testorders erfordern eine konkrete Vorschau und ausdrückliche
Bestätigung. Es werden keine automatischen oder echten Live-Orders freigegeben.

Die Laufzeitdatei `.runtime/runtime.env` setzt die Handelssperre vor `.env`.
Eine spätere bewusste Freigabe muss dort erfolgen, gefolgt von
`systemctl --user restart blackgate-analytics-app.service`. Eine Schlüsselfreigabe
allein entsperrt nichts. `ALPACA_ACCOUNT_ID` ist an das überprüfte Paper-Konto
gebunden; bei Kontowechsel sind Identität und Freigabe erneut zu prüfen.

Die historische Stresstab-Logik ist illustrativ. Der neue Marktstress-Bereich
ist beobachtende Forschung und kein kalibriertes Prognosemodell.

## Manueller Paper-Desk: freigegebener Betrieb

Nach bestandenen 55 Tests und bestätigter Paper-Kontozuordnung ist der manuelle
Desk in dieser Installation über `.runtime/runtime.env` freigegeben. Die
Auslieferungs-Voreinstellung bleibt gesperrt. Bots, direkte Schnellorders und
REST-/MCP-Schreibwege bleiben gesperrt; jede manuelle Order benötigt ihre
eigene Vorschau und Bestätigung in der Anwendung, keine Chat-Freigabe.

Im Alpaca-Tab unter **Optionen suchen** den Basiswert und ein Verfallsfenster
eingeben, anschließend Verfall, Call/Put, Strike und Kauf/Verkauf auswählen.
**In Einzelorder übernehmen** füllt das Ticket einschließlich Quote als
editierbarem Limit vor. **Als Kombinations-Leg hinzufügen** übernimmt bis zu
vier Legs; das gemeinsame Netto-Limit wird anschließend selbst eingegeben.
Ein neues Einzelorder-Ticket verwirft alte Kombinations-Legs. **Ticket leeren**
löscht nur die aktuelle Eingabe, niemals das dauerhafte Orderjournal.

Auch die Call-/Put-Tabellen im ursprünglichen Options-Screener bieten jetzt
eine direkte Ticketübergabe. Die Übernahme sendet keine Order und umgeht weder
Broker-Handelbarkeit noch Quote-, Bestands- oder Deckungsprüfung. Eine frische
Indicative-Quote ist keine offizielle OPRA-Quote:
[Alpaca-Feeddefinition](https://docs.alpaca.markets/us/reference/optionlatestquotes).
