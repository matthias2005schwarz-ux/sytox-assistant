# SYTOX: Optionale Cloud-KI ab Version 0.3.13

SYTOX bleibt ein Windows-Programm mit lokaler Oberfläche, lokaler Spracherkennung,
lokaler Sprachwiedergabe, SQLite-Gedächtnis und lokaler Windows-Steuerung.
Nur die **KI-Modellanfragen** können optional an die OpenAI API gehen.

## Einrichtung

1. Ein eigenes OpenAI-API-Konto und eine aktive Abrechnung sind erforderlich.
   Ein ChatGPT-Plus-/Pro-Abo enthält **keine** API-Nutzung automatisch.
2. Erstelle deinen API-Schlüssel nur im OpenAI-API-Dashboard.
   **Schicke den API-Schlüssel niemals in einen Chat, ein GitHub-Issue oder an Codex.**
3. SYTOX → **Einstellungen** → **OpenAI-API-Schlüssel**.
   Den Schlüssel dort einfügen und **Speichern**. Er wird im Windows-
   Anmeldedatenspeicher abgelegt, nicht in der Konfigurationsdatei.
4. Setze **Cloud-KI für normale Chats** aktiv, wenn du Online-Antworten möchtest.
   Das kleine Standardmodell lautet `gpt-4.1-mini`; es kann geändert werden.
5. Optional und **getrennt davon**: **Cloud-KI für Programmieraufträge**.
   Dadurch nutzt der lokale SYTOX-Agent `gpt-4.1` als Standardmodell.
   Die Werkzeuge laufen weiterhin lokal mit den vorhandenen Freigaben.

Die beiden Cloud-Schalter sind nach der Installation und beim Update **aus**.
Wenn der API-Schlüssel fehlt oder die Verbindung fehlschlägt, erhältst du eine
Fehlermeldung; die Anwendung schaltet nicht heimlich auf einen anderen Anbieter um.

## Datenschutz, Kosten und Grenzen

- Beim **Cloud-Chat** werden die gesendete Frage, ein begrenzter Chatverlauf
  und gegebenenfalls relevante Erinnerungen, Bildschirmbeobachtungen oder
  Rechercheauszüge an OpenAI übertragen.
- Beim **Cloud-Coding** können zusätzlich Code, Projektauszüge, lokale
  Werkzeugergebnisse und Prüfergebnisse in KI-Anfragen enthalten sein.
  Schalte Cloud-Coding nur für Projekte frei, deren Inhalte du dort
  verarbeiten lassen möchtest.
- Windows-Aktionen werden nicht auf einem Cloud-Computer ausgeführt,
  sondern nur durch die vorhandenen lokalen SYTOX-Werkzeuge mit Sicherheitsprüfungen.
- Ein Cloud-Modell hat keine garantierte Antwortzeit und nicht automatisch
  alle Funktionen der ChatGPT-App. API-Ausfälle, Kontolimits, Modellzugriff
  und weitere Kosten bleiben möglich.
- Für die OpenAI-Chat-Completions-Anfragen setzt SYTOX `store: false`.
  Prüfe gegebenenfalls die Daten- und Aufbewahrungsrichtlinien deines API-Kontos.
- Nicht aktivierte Funktionen senden **keine** OpenAI-API-Anfragen.
  Die bisherige lokale Ollama-Variante bleibt vollständig erhalten.

## Was ist mit „Hi“?

Exakte Begrüßungen werden unverändert sofort lokal beantwortet, ohne
Cloud-Anfrage oder Modellstart. Für freie Gespräche greift das ausgewählte
Cloud-Modell nur dann, wenn der Cloud-Chat aktiv ist.

## Fehlerbehebung

- **401:** API-Schlüssel falsch, abgelaufen oder widerrufen.
- **429:** API-Budget oder Nutzungsgrenze überschritten.
- **Cloud-Modell nicht erreichbar:** Prüfe den gewählten Modellnamen und
  den Zugriff deines API-Projekts.
- **Credential Store nicht verfügbar:** Auf Windows die Anmeldeinformations-
  verwaltung/den Benutzerkontext prüfen, nicht den Schlüssel in `settings.json` ablegen.

**Keine unbegrenzte Nutzung:** Die API hat eigene Nutzungslimits und
verbrauchsabhängige Kosten. Ein eigener GPU-Server ist eine alternative
Möglichkeit, etwa mit einem sicher über VPN erreichbaren Ollama-Endpunkt.
