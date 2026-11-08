# Formatierte Antworten im Desktop-Chat

SYTOX zeigt Antworten im Hauptchat und in Qwen-Projekten als formatiertes Markdown:
Überschriften, fett/kursiv hervorgehobenen Text, Listen, Zitate und Tabellen.
Nutzernachrichten bleiben als unveränderter Klartext sichtbar.

Code steht in eigenen dunklen Karten mit Sprachangabe, einer Schrift mit fester
Zeichenbreite und Syntaxfarben. Python, JavaScript/TypeScript, C/C++, C#, Java,
Go und Rust erhalten passende Schlüsselwort-/Kommentarfarben. Unbekannte Sprachen
werden weiterhin lesbar dargestellt; die einfache lexikalische Hervorhebung ist
kein Compiler und kein vollständiger Sprachparser.

Während einer Antwort aktualisieren sich bestehende Text- und Codebereiche.
Noch nicht abgeschlossene Codeblöcke zeigen „wird ergänzt“. Der Kopierbutton
erscheint nach dem schließenden Markdown-Zaun und übernimmt nur den Originalcode,
ohne Erklärung oder Zäune. Eine kurze „Kopiert“-Bestätigung zeigt die Übernahme an.
Der übergeordnete Kopierbutton kopiert weiterhin die ganze ursprüngliche Antwort
als Markdown. Speicherung und Text-Export bleiben unverändert.

Lange Codeblöcke erhalten einen begrenzten sichtbaren Editorbereich mit eigenen
Scrollbalken; der gesamte Text bleibt auswählbar und kopierbar. Gestreamte
Ergänzungen folgen dem Ende, solange dort gelesen wird; manuelles Zurückscrollen
und Textauswahlen werden erhalten. Sehr lange Codezeilen werden horizontal
gescrollt statt den Chat über den Fensterrand zu vergrößern.

Die Darstellung verwendet native Qt-Widgets und benötigt keine neuen Pakete,
keinen Webserver und keinen Browser. HTML aus Antworten wird nicht interpretiert;
Bilder oder andere externe/lokale Ressourcen werden nicht automatisch geladen.
Nur ausdrücklich aktivierte HTTP-/HTTPS-Links dürfen den normalen Browser öffnen.
Datei-, Daten- und Skriptlinks bleiben gesperrt. Angezeigter Code wird nicht ausgeführt.

## Reproduzierbare native Vorschau

```bash
python tools/chat_render_preview.py chat-vorschau.png
```

Das Werkzeug erzeugt einen Screenshot des echten Hauptfensters mit einer lokalen
Beispielantwort in einem temporären Datenprofil. Es fragt kein Modell an, öffnet
keine Nutzerdateien und benutzt weder Mikrofon noch Netzwerk. Die Vorschau dient
der Darstellungskontrolle; echte Windows- und Hardwaretests bleiben erforderlich.
