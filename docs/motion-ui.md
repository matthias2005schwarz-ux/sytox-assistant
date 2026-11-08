# Native Animationen und visuelles Feedback

Die schwarz-rote Oberfläche verwendet feinere dunkle Flächen, klare Fokusrahmen,
dezente rote Verläufe und besser unterscheidbare gedrückte/deaktivierte Buttons.
Die vorhandenen SYTOX-Logos bleiben Bestandteil der nativen Oberfläche.

Buttons erhalten kurze Hover-, Fokus- und Druckübergänge. Die zusätzliche
Zeichnung fängt keine Eingaben ab und verschiebt keine Bedienelemente. Neue
Code-Kopierbuttons werden auch während einer gestreamten Antwort angebunden.
Das Eingabefeld hebt beim Schreiben den umgebenden Rand hervor; der Fokus bleibt
im tatsächlich gewählten Steuerelement.

Neue Nachrichten, die Startansicht und eingeblendete Bereiche erscheinen mit
kurzen Fades. Alte Nachrichten beim Laden eines Verlaufs werden nicht einzeln
animiert. Laufende Antworten starten keine neue Animation pro Token. Nach dem
Übergang werden die temporären Transparenzeffekte entfernt; vorhandene Schatten
werden nicht ersetzt. Aus- und Einblenden beendet keine KI- oder Sprachaufträge.

Die drei Aktivitätspunkte neben dem Antwortstatus bewegen sich nur während einer
laufenden Antwort oder eines laufenden Hauptauftrags. Bei Abschluss, Fehler,
abgeschlossener Unterbrechung, Verbergen oder Minimieren endet die Bewegung. Im
Ruhezustand bleibt ein kleiner gedämpfter Punkt. Dies ist eine Aktivitätsanzeige,
keine erfundene Fortschritts- oder Geschwindigkeitsmessung.

Sowohl die gesamte Antwort als auch einzelne Codeblöcke bestätigen das Kopieren
kurz mit „Kopiert“. Kopiert wird der ursprüngliche Text; die Bestätigung gehört
nicht zum Inhalt. Die Rückmeldung besitzt einen an den Button gebundenen Timer.

Unter **Einstellungen → Darstellung → Animationen reduzieren** lassen sich die
neuen Übergänge deaktivieren. Die Aktivitätspunkte bleiben dann statisch. Die
Auswahl wirkt sofort nach dem Speichern und bleibt über Neustarts erhalten.
Vorhandene Ansichtspräferenzen werden dabei mitgespeichert. Die Optionen können
in kleineren Fenstern gescrollt werden; der Speichern-Button liegt außerhalb des
Scrollbereichs und bleibt erreichbar.

## Vorschau reproduzieren

```bash
python tools/motion_preview.py /pfad/zur/vorschau
```

Das Werkzeug erfasst echte Fensterbilder mit lokalen Beispieldaten in einem
temporären Profil. Die Vorschau ist ausdrücklich als Darstellung ohne Modell-
anfrage gekennzeichnet. Sie verwendet weder Mikrofon noch Netzwerk. Wenn `ffmpeg`
bereits installiert ist, entsteht zusätzlich ein kurzes MP4 aus unveränderten
Fensteraufnahmen; ohne Encoder bleibt der PNG-Screenshot. Es werden keine Pakete
nachinstalliert.

Die Qt-Prüfungen decken Eingaben, Widget-Lebensdauer, dynamische Buttons,
Animationseffekte, reduzierte Bewegung, Fensterzustände und die echte
Streaming-Anbindung ab. Ein Windows-/High-DPI-Praxistest bleibt zusätzlich nötig.
