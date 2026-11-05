# SYTOX Bildschirmhilfe (Entwicklungszweig)

Der Modus startet beim App-Neustart immer **AUS**. Er wird über die
rechte Steuerzentrale oder über Sprache aktiviert.

- **Start:** „Hey Sytox, schau auf meinen Bildschirm“ oder
  „Sytox, guck auf meinen Bildschirm“.
- **Frage:** „Was ist das für ein Fehler?“ oder „Wie mache ich das?“
  Solange die Freigabe aktiv ist, erzeugt jede Frage genau einen aktuellen
  Screenshot des Hauptmonitors und sendet ihn an das **lokale Ollama**
  auf `127.0.0.1:11434`.
- **Stop:** „Sytox, verlass meinen Bildschirm“ oder „Bildschirmhilfe beenden“,
  alternativ der Stop-Knopf. Weitere Aufnahmen werden sofort verhindert.
  Bereits laufende Antworten werden nicht mehr angezeigt.

**Einrichtung:** In der Bildschirm-Karte „Bildmodell einrichten“ anklicken
und das lokale Vision-Modell `qwen3-vl:2b` auswählen, ca. 1,9 GB
Modell-Download. Ollama muss Version 0.12.7 oder neuer sein. Ein bestehendes
Chat-Coder-Modell bleibt unverändert. Es ist keine Installation ohne Klick vorgesehen.

**Datenschutz:** keine Daueraufnahme, kein periodischer Zugriff,
keine Screenshot-Dateien. Die Bilddaten gehen ausschließlich an den lokalen
Ollama-HTTP-Endpunkt; Redirects sind deaktiviert. Nur Textfrage und
Textantwort werden im SYTOX-Chat gespeichert. Während der Auswertung
kann eine bereits gesendete lokale HTTP-Anfrage noch auslaufen, obwohl
nach „Stop“ keine neuen Screenshots angefertigt oder Antworten angezeigt werden.

**Grenzen:** Hauptmonitor statt sämtlicher Monitore; geschützte Fenster
können schwarze Screenshots liefern; 2B-Visionmodelle können kleine Schrift
oder komplexe Fehlermeldungen falsch interpretieren. Echter Mikrofon-, Anzeige-,
Modell- und Stopp-Test auf dem Ziel-Windows-PC steht noch aus.
Keine neue veröffentlichte Windows-Version und kein Release-Installer.
