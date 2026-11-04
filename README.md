# Entwicklungsstand: Automatische Webrecherche (noch kein Release)

- **Ohne gesonderten Suchbefehl:** Bei kurzen öffentlichen Wissensfragen wie „Wer ist Jenna Ortega?“ sucht SYTOX selbstständig nach aktuellen Quellen. Reine Programmieraufträge und Steuerfragen wie „Wie weit bist du?“ lösen keine automatische Suche aus.
- **Auch während des Programmierens:** Die getrennte Nebenunterhaltung kann Web-Suchtreffer abrufen, während der Hauptagent weiterläuft. Sie erhält dadurch **keine** Schreib-, PC- oder Agentenwerkzeuge.
- **Quellen und Grenzen:** Ein Lesezugriff sucht Bing-RSS-Suchergebnisse mit DuckDuckGo-HTML als Ausweichlösung. Antworten nennen Links zu Suchtreffern; Snippets sind keine unabhängig überprüften Fakten. Für umfassende Webseitenanalysen steht dem Hauptagenten weiterhin der bestehende Browser zur Verfügung.
- **Verfügbarkeit:** Internet erforderlich. Suchanfragen werden an den jeweiligen Suchanbieter gesendet; keine Anmeldedaten oder Browserprofile werden für die Suche verwendet. Wenn der Anbieter nicht erreichbar ist, wird keine erfolgreiche Echtzeitrecherche vorgetäuscht.
- **Tests/Veröffentlichung:** Automatisierte Regressionstests sind ergänzt; Live-Suchanbieter, echtes Ollama- und Windows-Sprachverhalten müssen praktisch getestet werden. Es wurde **keine neue Windows-EXE** veröffentlicht.

---

# Neu im Entwicklungszweig: Automatische Erkennung von Programmiersprachen und Entwicklungswerkzeugen

- **Neue Agent-Werkzeuge:** `toolchain_inspect` prüft vorhandene Projektdateien, empfiehlt anhand des Auftrags eine Sprache und meldet fehlende Compiler, ohne Code auszuführen oder Software zu installieren.
- **Sprachen:** Python, JavaScript, TypeScript, C#, Java, C, C++, Go, Rust sowie Erkennung von PHP, Lua und Kotlin. Für PHP, Lua und Kotlin ist aktuell noch kein automatisches Installationspaket freigegeben.
- **Windows-Installation auf ausdrücklichen Wunsch:** `toolchain_install` nutzt ausschließlich fest hinterlegte winget-Paket-IDs (z. B. .NET SDK, Node.js LTS, Python, Temurin JDK, LLVM, Go, rustup). Der Nutzer sieht vor **jedem** Installationsversuch das genaue Paket und muss ausdrücklich zustimmen. Es gibt weder eine verdeckte Installation noch eine frei wählbare Paket-ID.
- **Wichtig:** TypeScript benötigt zusätzlich zum Node.js-Paket die projektbezogene TypeScript-Installation; C/C++ und Rust können weitere Windows-Build-Werkzeuge benötigen. Ein erfolgreicher winget-Lauf beweist noch keinen funktionierenden Compiler: eine erneute Prüfung bzw. ein Neustart kann nötig sein.
- **Projekt-Builds:** `run_command` erfordert für ausführbare Entwicklungsbefehle weiterhin Freigaben. Der Agent kann einige zusätzliche echte Projekt-Builds als Prüfung bewerten, aber ein grüner Compileraufruf ist **kein** Beleg für eine getestete Windows-EXE.
- **Lieferstand:** Quellcode und automatisierte Regressionstests im Entwicklungszweig; echte Installations- und Build-Tests auf dem Nutzer-PC sowie eine veröffentlichte EXE/Installer-Version sind noch offen.

---

# Entwicklungsstand: Sprechen während SYTOX programmiert

### Natürliche Arbeitsunterbrechung und Fortsetzung

SYTOX kann neben den bisherigen kurzen Befehlen auch höfliche, natürlich formulierte Anweisungen unterscheiden:

- **Auftrag pausieren:** „Hör kurz auf zu programmieren“, „Kannst du bitte kurz aufhören zu programmieren?“, „Mach eine Pause“ oder „Warte mit dem Programmieren“. Die Agent-Schleife erhält einen Stoppwunsch und speichert einen wiederaufnehmbaren Zwischenstand; bereits laufende externe Aktionen lassen sich nicht immer sofort unterbrechen.
- **Wieder aufnehmen:** „Mach wieder weiter“, „Programmiere weiter“, „Setz die Arbeit fort“ oder „Fang wieder an“. Bei noch laufendem Abbruch wird der Wiederbeginn nach dem Abschluss des alten Threads eingeplant.
- **Nur Stimme stoppen:** „Sei still“ oder „Hör auf zu reden“ lässt den Programmierauftrag weiterlaufen.
- **Gewöhnliches Gespräch:** Fragen oder Sätze wie „Hör nicht auf zu programmieren“ sind kein Abbruchbefehl. Die getrennte Nebenunterhaltung bleibt verfügbar.
- **Sicherheit:** Mehrdeutige Sätze führen nicht zu einer verdeckten PC-Aktion. Die freie Unterhaltung verwendet keine Agent-Werkzeuge. Das System kann nicht garantieren, jede denkbare Formulierung korrekt zu verstehen. Pausen/Auftragsfortsetzungen erfordern weiterhin, dass SYTOX auf dem Rechner läuft.



- **Parallel statt Stopp:** Der Haupt-Agent bearbeitet den ursprünglichen Auftrag im eigenen QThread weiter. Fragen per Texteingabe oder Stimme werden währenddessen in einer separaten, temporären Nebenunterhaltung beantwortet. Diese Nebenunterhaltung hat bewusst **keine PC-/Dateiwerkzeuge** und verändert den laufenden Auftrag nicht.
- **Bedienung:** Im Bereich „Agent Control“ auf „Während der Arbeit chatten“ klicken, oder während eines laufenden Auftrags einfach eine weitere Frage schreiben bzw. nach „Hey Sytox“ sprechen.
- **Status:** „Wie weit bist du?“, „Arbeitest du noch?“ oder „Was machst du gerade?“ melden den tatsächlich bekannten Status; es werden keine erfundenen Prozentwerte angegeben.
- **Stopp eindeutig:** „Stopp“ fordert das Beenden des Auftrags an. „Sei still“ unterbricht lediglich das Vorlesen. Der Werkzeug-Agent behält sämtliche bisherigen Freigabeprüfungen.
- **Grenzen:** Der PC und SYTOX müssen eingeschaltet bleiben. Bei einem einzigen lokalen Ollama-Modell kann die parallele Sprachantwort die Modellarbeit verlangsamen oder in Ollama warten, ohne den Agent-Thread abzubrechen. Sprachqualität, tatsächliche Multitasking-Leistung und Mikrofon-Interaktion müssen auf dem Anwender-PC erprobt werden. Noch kein neues Installationspaket mit dieser Funktion als Release bestätigt.

## Neu im aktuellen Entwicklungsstand: Sprach- und Desktop-Steuerung (noch ohne Release-Installer)

- Im rechten Panel unter **Agent Control → Windows-Steuerung** können geöffnete Fenster angezeigt und Programme anhand von Windows-Startmenü-/Desktop-Verknüpfungen gesucht werden.
- Ein Fenster wird nur **nach deiner Bestätigung** in den Vordergrund gebracht. Ein gefundenes Programm wird nur nach Auswahl und ausdrücklicher Bestätigung gestartet. Keine versteckten Shell-Befehle oder automatische Texteingabe.
- Nach aktiviertem lokalem Gesprächsmodus mit „Hey Sytox“ funktionieren zusätzliche Befehle wie **„Zeig mir die offenen Fenster“**, **„Suche Programm Firefox“**, **„Öffne Editor“** und **„Mikrofon ausschalten“**. Die ersten drei öffnen nur die sichere Windows-Steuerzentrale; es wird dadurch noch nichts gestartet. Alle anderen Sprachaufträge laufen wie bisher über Agent/Tool-Freigaben.
- Die Offline-Spracherkennung benötigt weiterhin das deutsche Vosk-Modell und ein funktionsfähiges Mikrofon. Für Windows-Tests wurden simulierte Desktop-/Zustimmungsprüfungen ergänzt; reale Mikrofon- und Desktop-Hardware müssen auf dem eigenen Windows-PC geprüft werden.
- Diese Änderungen sind **Quellcode**. Eine neue, erfolgreich verifizierte Windows-EXE und ein Installer wurden für diesen Entwicklungsstand noch nicht bereitgestellt.

# SYTOX Assistant – Windows 0.3.2 (Black & Crimson Desktop Design)

## Neu in 0.3.2: Vollständige Neugestaltung der nativen Qt-Oberfläche

- **Farbwelt:** Tiefschwarz, Graphit und Dunkelrot, ohne die bisherige Pink-/Navy-Palette. Grüne/gelbliche Statusfarben werden ausschließlich für echte Bereit-/Warnzustände verwendet.
- **Fenster:** Überarbeitete Chat-Navigation links, großzügiger Nachrichtenbereich in der Mitte und übersichtliche Steuerkarten für KI, Agent, Sprache und Aktivitäten rechts. Keine Website oder WebView.
- **Neuer Chat:** Begrüßungskarte mit funktionierenden Vorschlägen, die Text in das Eingabefeld übernehmen (nichts wird ohne Klick auf Senden abgeschickt).
- **Chat:** Unterschiedliche dunkelrote Benutzer- und neutrale KI-Sprechblasen, sichere Nur-Text-Anzeige, ruhige Abstände und besser lesbare Schrift.
- **Mikroanimationen:** Kurze, nicht blockierende Einblendungen statt dauerhaft blinkender Effekte. Vektor-Logo mit dezentem rotem Licht.
- **Bestand:** Alle Agent-, Ollama-, Sprach- und Datenspeicherfunktionen bleiben im selben Projekt. Keine Migration und kein Löschen alter Chats.
- **Test:** UI-Vertragsprüfungen plus Windows-Komponententests, nativer Qt-Start, EXE- und Installer-Test in GitHub Actions. Die finale optische Wirkung und Bildschirm-DPI müssen zusätzlich auf dem Anwender-PC beurteilt werden.

# SYTOX Assistant – Windows 0.3.1 (Mikrofon-Diagnose)

## Neu in 0.3.1: Interaktiver Mikrofon- und Sprachunterbrechungstest

Öffne SYTOX und klicke rechts auf **„Mikrofon und Unterbrechung testen“**.

1. **Mikrofon testen:** Sprich 5 Sekunden. SYTOX misst dein tatsächliches Mikrofonsignal in 16-kHz-PCM; wenn kein Gerät, keine Daten oder kaum Lautstärke vorhanden sind, wird das angezeigt.
2. **Spracherkennung testen:** Sprich „Hey Sytox, Test“ und warte nach dem Satz kurz auf die Erkennung. Vosk wird benötigt (lade das deutsche Sprachmodell über den Button in der App). In dieser Diagnose werden **keine PC-Aktionen** ausgeführt.
3. **Sprachunterbrechung testen:** SYTOX spricht länger. Sag währenddessen „Stopp“ und werde kurz still. Die Diagnose prüft, dass die laufende Windows-TTS beendet wird und zeigt das Ergebnis.

Die Diagnose speichert keine Sprachaufnahmen und überträgt keine Mikrofondaten. Die Tests benötigen Zugriff auf *dein* Mikrofon und müssen deshalb auf deinem Windows-Rechner ausgeführt werden. Die GitHub-CI überprüft den Start der Anwendung und simulierte Audio-Testwerte, aber keine echte physische Akustik.

## Neu in 0.3.0

- Sprachsteuerung weiterentwickelt: „Hey Sytox“ bzw. „Stopp“ kann laufende
  Sprachausgabe unterbrechen. Nach „Hey Sytox“ ist eine Folgefrage möglich.
  Auf Wunsch unterbricht auch ein längerer Satz ohne Wakeword; das erhöht
  allerdings die Gefahr, dass die eigene Lautsprecherausgabe erkannt wird.
  **Für Sprachunterbrechungen sind Kopfhörer empfehlenswert.** Die Reaktionszeit
  hängt außerdem davon ab, wie schnell Vosk eine Äußerung als beendet erkennt.
- Windows-Systemstimme spielt über asynchrones SAPI ab und reagiert auf Stopp;
  Piper/Edge-Audio kann weiterhin über den vorhandenen Qt-Player gestoppt werden.
- Option in Einstellungen, den Gesprächsmodus beim Programmstart automatisch
  zu aktivieren (standardmäßig AUS; aktiviert das Mikrofon, auch im Tray).
- Deutsches Vosk-Modell direkt aus dem Sprachbereich der Anwendung herunterladen,
  mit Fortschritt, Abbrechen, begrenzten Größen und geschützter ZIP-Extraktion.
  Download erfolgt nur mit Zustimmung; Mikrofonaufnahmen bleiben lokal.
- Sprachbefehle wie „Hey Sytox, öffne Discord“ werden an den vorhandenen
  Agenten weitergereicht. Die Eingriffsfreigaben für PC-Aktionen bleiben bestehen.
  Wird bei im Tray versteckter App eine Freigabe nötig, öffnet sich das Fenster.
- Echte Mikrofon-/Lautsprechertests und Sprachgenauigkeit müssen auf dem PC
  geprüft werden. Der CI-Test simuliert den Download und die TTS-Abbruchlogik.
- Falls die Windows-GUI/Installer-Pipeline erfolgreich abschließt, werden
  die Builds in GitHub Actions als Artefakte verfügbar.

# SYTOX Assistant – Entwicklungsstand 0.2.9 (Ollama auf Knopfdruck einrichten)

## Neu in 0.2.9

- **Direkt im Fenster:** Rechts auf **Einrichten** klicken, ein Modell auswählen und **Ollama + Modell einrichten** drücken. Erst nach expliziter Bestätigung startet die Installation.
- **Windows-Paketmanager:** Ist Ollama nicht installiert, installiert SYTOX ausschließlich das Paket `Ollama.Ollama` aus der offiziellen `winget`-Quelle. Kein ungeprüfter Download und keine verdeckte Ausführung über eine Shell. Falls winget fehlt, ist ein Link zur offiziellen Ollama-Webseite verfügbar.
- **Lokaler Ollama-Server:** Läuft Ollama noch nicht, versucht SYTOX, `ollama serve` im Hintergrund zu starten. Bestehende Ollama-Instanzen werden weiterverwendet.
- **Modell-Download:** Lädt das ausgewählte Modell per Ollama-API mit Fortschrittsanzeige. Standard bleibt `qwen2.5-coder:7b`; alternativ ist `qwen2.5-coder:3b` für langsame CPUs / weniger RAM auswählbar. Der Download dauert je nach Internet, Speicherplatz und Modell mehrere Minuten und kann abgebrochen werden.
- **Verifizierter Abschluss:** Erst wenn Ollama das Modell nach dem Download in seiner Modellliste meldet, wird es als einsatzbereit gespeichert. Das Herunterladen und die Installation erfordern Internet; die späteren Chatantworten sind lokal.
- **Einschränkungen:** Keine automatische Neuinstallation auf fremden Rechnern, keine Hintergrunddownloads ohne ausdrücklichen Klick. Der Nutzer muss den Installations- und Modell-Download ausdrücklich genehmigen. Die Antwortqualität und Reaktionsgeschwindigkeit eines lokalen 3B-/7B-Modells sind nicht mit ChatGPT gleichzusetzen.
- **Tests:** Unit-Tests für lokale Endpunkte, sichere Paketmanager-Argumente, Abbruch, Erfolgsvalidierung und Qt-Klicks plus vollständiger Windows-Build-Workflow. **Ein Download von mehreren GB und eine reale Ollama-Erstinstallation werden im CI nicht ausgeführt.**

---

# SYTOX Assistant – Entwicklungsstand 0.2.9 (Ollama-Einrichtung und Verbindungsstatus)

## Neu in 0.2.9

- **KI-Verbindungsstatus direkt im Hauptfenster:** SYTOX zeigt nach dem Start ausdrücklich, ob Ollama erreichbar ist und ob das ausgewählte Modell installiert ist. Die App behauptet nicht länger, dass die KI bereit ist, wenn nur das Fenster geöffnet wurde.
- **Einrichtungsdialog:** Offizieller Ollama-Windows-Download, kopierbarer `ollama pull ...`-Befehl und erneuter Verbindungscheck. Weder Programme noch Modelle werden ohne ausdrückliche Handlung des Benutzers installiert.
- **Keine blockierte Oberfläche:** Die Startprüfung läuft in einem Qt-Hintergrundthread mit Zeitlimit; neue Einstellungen lösen danach eine weitere Prüfung aus.
- **Prüfungen:** Zusätzliche automatisierte Tests für nicht erreichbare Ollama-Server, fehlende Modelle, ungültige Adressen und ungültige Modellnamen.
- **Voraussetzungen:** Ollama selbst und ein kompatibles heruntergeladenes Modell sind weiterhin separat erforderlich. Eine erfolgreiche Installer-Prüfung auf einer GitHub-Windows-VM belegt nicht die Qualität des lokalen KI-Modells oder seiner Antwortgeschwindigkeit.

## Windows-Build-Status

Die Basisversion 0.2.7 wurde in einem echten GitHub-Actions-Windows-Runner gebaut und inklusive Installation, Start und Deinstallation erfolgreich geprüft. Version 0.2.9 muss nach diesen Änderungen erneut per Windows-CI getestet werden.

---

# SYTOX Assistant – Entwicklungsstand 0.2.7 (Windows Build/Installer-Verifikation)

## Neu in Version 0.2.7

- Windows-CI erstellt eine portable Windows-App (`dist/SYTOX_Assistant/`) und einen Inno-Setup-Installer.
- Echter *automatisierter* Installations-Smoketest in einer **isolierten GitHub-Actions-Windows-VM**: Installieren, die installierte EXE mit `--smoke-test` starten, deinstallieren, erhaltene Benutzerdaten kontrollieren. Dieser Test läuft **nicht** auf Linux. Für 0.2.7 lief er in GitHub Actions auf Windows erfolgreich durch.
- Beim EXE-Startabsturz wird `startup_error.log` unter `%APPDATA%\SytoxAssistant` geschrieben, um Fehler eines Windows-GUI-Programms ohne Konsolenfenster zu diagnostizieren.
- Build nimmt die Installer-Quellen in das für Self-Development bereitgestellte Bundle auf.
- Die Windows-CI veröffentlicht die fertige EXE (als Verzeichnis-ZIP) und den Installer als getrennte Build-Artefakte **nur nach** erfolgreichen Tests. Zum Ausführen muss der Projektordner als GitHub-Repository veröffentlicht und die Workflow-Aktion gestartet werden. Für Version 0.2.7 wurde ein Windows-Installer in GitHub Actions erfolgreich erzeugt und getestet.
- **Eine VM-Prüfung ist kein Ersatz für die Prüfung auf dem eigenen PC** (Audio, PC-Steuerung, Antiviren-/Rechteumgebung, Tray, Autostart, Performance).

### Windows Build / automatisierte Tests

1. Auf Windows mit Python 3.12, PowerShell und Inno Setup 6: `Setup_Windows.ps1` ausführen (interaktives Setup).
2. Tests: `Windows_Smoke_Test.ps1 -BuildExe`.
3. Installer: `Build_Installer.ps1 -SkipExeBuild`.
4. Auf GitHub: Projektinhalt als Repository-Root hochladen; unter `Actions` den Workflow **SYTOX Windows Checks** starten. Nur die isolierte CI-VM führt `Installer_Install_Smoke_Test.ps1` aus; es installiert bewusst **nicht** auf deinem normalen PC. Bei erfolgreichem Workflow die zwei Artefakte herunterladen.

**Status 0.2.7:** Der Windows-Installer wurde am 03.11.2026 auf einem GitHub-Actions-Windows-Runner erfolgreich gebaut und per Installations-/Deinstallations-Smoke-Test geprüft. Das ersetzt keine Tests auf dem eigenen PC.

---

# SYTOX Assistant – Entwicklerstand 0.2.5 (Windows-Installer und UI)

**Status: NICHT FERTIG.** 77 automatisierte Python-Tests bestanden (unter Linux, mit simulierten Qt-/Windows-Funktionen). Native Windows-EXE, Inno-Installer, Tray und Audio wurden in dieser Umgebung **noch nicht praktisch getestet**. Aktuell liegt nur Quellcode und ein Windows-Buildablauf vor, keine fertige Windows-EXE.

## Änderung in 0.2.5: Installer, Ein-Instanz-Start und Design

- **Optionaler Autostart:** Inno Setup bietet eine standardmäßig deaktivierte Option, den Assistenten bei Windows-Anmeldung mit `--background` ins Tray zu starten. Das startet *nicht* automatisch das Mikrofon. Beim Update ist die zuvor gewählte Option neu auswählbar; bei Abwahl wird der alte HKCU-Run-Eintrag entfernt.
- **Ein-Instanz-Verhalten:** Bei einem zweiten Desktop-Start empfängt der bereits laufende Assistent eine lokale Nachricht und öffnet sein Fenster, statt eine zweite Instanz zu erzeugen. Der Hintergrund-Autostart öffnet eine laufende Instanz nicht. Ist die Taskleiste ohne Tray-Unterstützung, wird das Fenster regulär eingeblendet.
- **Tray-Menü:** Schließen mit X versteckt das Fenster, solange das Tray verfügbar ist; „SYTOX vollständig beenden“ schließt die App kontrolliert und fragt bei laufenden Aufgaben nach.
- **Benutzerfreundlicher Installer:** Pro-Benutzer-Installation ohne Administratorrechte, optionale Desktop-Verknüpfung, Inno-Setup-Upgrade-ID, keine Löschung von Chats/Settings im Roaming-Profil bei Deinstallation. Für ein Upgrade muss SYTOX beendet werden.
- **Designänderung:** Einheitlicheres dunkles Blau mit magenta Akzenten, überarbeiteter Chatkopf, Buttons, Listen, Eingabebereich, Statuschip und Tray-Icon. Das ist ein Implementierungsstand ohne visuell verifizierten Windows-Render-Test.
- **CI vorbereitet:** GitHub Actions kann bei einem GitHub-Checkout die Windows-Komponententests und den Qt/EXE-Smoketest ausführen, anschließend das Setup mit Inno Setup 6 kompilieren und als CI-Artefakt speichern. Nicht in diesem Chat auf Windows ausgeführt.
- **77 Tests unter Linux bestanden**, inklusive Ein-Instanz-Startverhalten mit Simulation, Start in Hintergrund, Freigaben und Installer-Vertragsprüfungen.

### Windows-Build und Testablauf

1. `powershell -ExecutionPolicy Bypass -File .\Setup_Windows.ps1` (benötigt Python, Netzwerk für Abhängigkeiten)
2. `powershell -ExecutionPolicy Bypass -File .\Windows_Smoke_Test.ps1 -BuildExe` (GUI/EXE prüfen; kein Test außerhalb der eigens angelegten GUI)
3. **Inno Setup 6** installieren, danach `powershell -ExecutionPolicy Bypass -File .\Build_Installer.ps1 -SkipExeBuild` zum Bauen des bereits getesteten Executables. Ohne `-SkipExeBuild` baut das Skript die EXE selbst erneut.
4. Erst nach positivem Test das erzeugte `installer\SYTOX_Assistant_Setup_0.2.5.exe` verwenden.

**Grenzen:** Der Installer wurde hier nicht nativ kompiliert oder auf Windows installiert. PC-Steuerung und Sprache müssen auf dem Zielrechner mit Einwilligung geprüft werden. Ein zusätzlicher Desktop-Starter kann nicht für eine Anwendung im ausgeschalteten PC weiterarbeiten.

## Änderung in 0.2.4: Windows-Smoke-Tests und EXE-Startprüfung

- `main.py --smoke-test` öffnet den Qt-Startpfad im Einmal-Testmodus, prüft die lokale UI-Initialisierung und beendet die Anwendung kontrolliert nach 350 ms; keine Ollama-Verbindung, keine PC-Eingaben.
- `Windows_Smoke_Test.ps1` prüft die Python-Tests, **echte Win32-Fensterauflistung**, pywinauto/UIA-Import und den vollständigen Qt-GUI-Start in einem temporären APPDATA-Verzeichnis. Optional `-BuildExe`: echte Windows-EXE bauen und mit Exitcode/30-Sekunden-Grenze überprüfen; optional `-InteractiveDesktop`: eigene isolierte Qt-Testoberfläche mit echter Unicode-Tastatureingabe prüfen.
- `.github/workflows/windows-ci.yml`: Windows-GitHub-Actions-Pipeline für Python 3.12, PySide6-Abhängigkeiten und EXE-Erstellung. Wird **erst ausgeführt**, wenn das Projekt in ein GitHub-Repository übertragen und der Workflow gestartet wird. **Es liegt noch kein Windows-CI-Ergebnis vor.**
- `Build_EXE.ps1` packt nun weitere Windows-Build-/Testdateien in die Quellcodekopie und die TTS-Module über PyInstaller.
- Neue plattformunabhängige Tests für den Startpfad und die Windows-Build-Skripte. Fehlendes PySide6 und fehlende Windows-Laufzeit in der aktuellen Umgebung verhindern den realen GUI/EXE-Test hier.

### Windows-Check auf Test-PC (erst wenn du testen möchtest)

1. `powershell -ExecutionPolicy Bypass -File .\Setup_Windows.ps1`
2. `powershell -ExecutionPolicy Bypass -File .\Windows_Smoke_Test.ps1`
3. Für EXE-Test: `powershell -ExecutionPolicy Bypass -File .\Windows_Smoke_Test.ps1 -BuildExe`
4. Nur auf ausdrücklichen Wunsch bei **sichtbarem Testfenster**: `powershell -ExecutionPolicy Bypass -File .\Windows_Smoke_Test.ps1 -InteractiveDesktop`. Die Testeingabe wird ausschließlich im selbst erzeugten Fenster vorgenommen.

**Noch offen:** native Windows-Ergebnisse, echte Installation durch Inno Setup und Prüfung von Mikrofon, TTS, Gmail sowie längeren Modellaufträgen. Nichts davon wird durch die neuen Cross-Plattform-Tests als bestanden erklärt.


## Änderung in 0.2.3: Self-Development und Langzeit-Checkpoints

- **Getrennte Selbstentwicklung:** `selfdev_prepare` legt nach Freigabe eine bearbeitbare Kopie in `assistant_source/` sowie eine unabhängige Original-Baseline im lokalen App-Datenordner an. Keine Änderung am laufenden Programm.
- **Änderungsvergleich:** `selfdev_review` listet veränderte/gelöschte/neue Dateien mit einem begrenzten Diff-Auszug auf. `write_file` kann die Arbeitskopie bearbeiten, ohne den Live-Code anzutasten.
- **Prüf- und Freigabekette:** `selfdev_validate` führt nach ausdrücklicher Freigabe Syntaxprüfung und Unit-Tests im Arbeitsordner aus. **Wichtig: Python-Tests führen ausführbaren Code auf dem PC aus; das ist keine Sandbox.** `selfdev_stage` erstellt nach erneuter Freigabe und nur bei unverändertem, zuvor grün geprüftem Stand ein ZIP im Projektordner (`selfdev_releases/`). Fehlende oder fehlgeschlagene Tests sowie nachträglich geänderte Dateien blockieren die Bereitstellung. Keine automatische Installation, kein Austauschen des laufenden Codes.
- **Windows-EXE-Quellcodekopie:** Das Build-Skript nimmt den Quellcode in ein `source_bundle` auf. Für Validierung aus der installierten Windows-EXE heraus wird zusätzlich eine reguläre Python-Entwicklungsumgebung mit Projekt-Abhängigkeiten benötigt. Unter Windows nicht praktisch getestet.
- **Längere Aufträge:** `record_progress` speichert beschränkte Fortschrittsnotizen, Nachweise und nächste Schritte in der SQLite-Task-Datenbank, sodass bei manueller Fortsetzung mehr Kontext verfügbar ist. Solche KI-Notizen gelten **nicht** als Nachweis einer erledigten Aufgabe; die bestehende explizite Abschlussprüfung bleibt aktiv.
- **62 automatisierte Tests unter Linux bestanden**, einschließlich Self-Development-Vergleich, Freigaben, fehlgeschlagener Tests, nachträglich geänderter Dateien, Staging und Wiederaufnahme von Arbeitsnotizen.
- **Noch nicht bestätigt:** Mehrstündiger durchgehender Modellbetrieb, Windows-End-to-End-Steuerung, sichere Isolation beliebiger Tests, selbsttätige Live-Upgrades oder Weiterarbeiten, wenn App/PC nicht laufen.

## Änderung in 0.2.2: Sprachunterhaltung (Quellcode)

- **Gesprächsmodus:** Lokale deutsche Spracherkennung mit Vosk. Standardmäßig wird er über „Hey Sytox“ aktiviert; nach einer Antwort sind Anschlussfragen für ein einstellbares Zeitfenster ohne erneutes Aktivierungswort möglich. Optional kann man *nach bewusstem Start* auf das Aktivierungswort verzichten.
- **Gegen Mithören der eigenen Antworten:** Das Mikrofon wird während der Auftragsbearbeitung und Sprachausgabe für die Befehlserkennung stummgeschaltet. Nach der Antwort wird es wieder freigegeben. Das ist noch **keine** frei unterbrechbare, voll-duplex Echtzeitunterhaltung.
- **Stimmen:** Windows-Systemstimme (lokal), Piper mit separater Offline-Stimme oder Microsoft Edge Neural (Online, nur nach ausdrücklicher Einwilligung). Deutsche und österreichische Stimmoptionen sind auswählbar. Bei Edge wird der gesprochene Text an Microsoft übertragen; das lokale Ollama-Modell bleibt davon unabhängig.
- **Audioverarbeitung:** Chat-Markdown wird fürs Vorlesen vereinfacht; bei längeren Antworten wird die Sprachausgabe gekürzt. Für Piper/Edge entstehen temporäre Audiodateien, die nach Wiedergabe gelöscht werden.
- **Windows-Einrichtung:** `Setup_Sprache.ps1` bietet den optionalen Download des deutschsprachigen Vosk-Modells an; `Setup_Windows.ps1` kann die Einrichtung abfragen.
- **54 automatisierte Tests unter Linux bestanden**, darunter 23 Tests für Sprach-Routing, Audioerzeugung mit simuliertem Online-Dienst, Fehlerfälle und WAV-Transkription. Eine vollständig getestete Windows-Sprachlösung ist das noch nicht: echte Mikrofon-/Lautsprechertests, TTS-Qualität, Audio-Gerätewechsel, Unterbrechung während Windows-TTS sowie EXE- und Installer-Tests fehlen.

## Änderung in 0.2.1: Windows-PC-Steuerung (Quellcode)

- **Neue Windows-App-Suche (`pc_find_apps`):** Findet Programme über Verknüpfungen im Startmenü und auf dem Desktop. Start nur nach konkreter Freigabe (`pc_open_app`); keine freie Shell-Ausführung durch das PC-Werkzeug.
- **Fensterwahl statt globaler Blindsteuerung:** `pc_list_windows` findet sichtbare Fenster mit ID/Position. Mit `pc_select_window` wird das Ziel ausdrücklich ausgewählt, nachdem der Benutzer zugestimmt hat. Spätere Eingaben sind daran gebunden.
- **Bedienelemente per Windows-UI-Automation:** `pc_inspect_window` liest nach Freigabe zugängliche Steuerelemente (pywinauto). `pc_click_control` kann das gewählte Element nach separater Freigabe anklicken. Nach einem Klick sind alte Element-IDs ungültig.
- **Gesteuerte Eingabe:** `pc_click` erlaubt nur Bildschirmkoordinaten im ausgewählten Fenster; nach Freigabe werden Position und Fokus erneut geprüft. `pc_hotkey` nutzt eine erlaubte Tastenliste. `pc_type_text` verwendet native Unicode-Eingaben (Umlaute, Emojis), ohne die Zwischenablage anzufassen.
- **Privatsphäre:** Windows-Fensterlisten und Accessibility-Inhalte werden nicht im Detail im lokalen Aktivitätsprotokoll/Checkpoint gespeichert; die lokale KI erhält diese Inhalte dennoch zur Bearbeitung. Programm-/Textaktionen bleiben freigabepflichtig.
- **31 automatisierte Tests unter Linux erfolgreich:** 16 vorherige plus 15 neue Tests, darunter Verweigerung, Fensterwechsel, Bereichsgrenzen, UI-Automation mit Test-Doppel und Unicode-Weitergabe.
- **Noch nicht unter Windows praktisch getestet:** Insbesondere Fenster-Fokussierung durch Windows, pywinauto-Bedienelemente, echte Tastatur-/Maussteuerung und das fertige Installer-Paket müssen auf dem Ziel-PC getestet werden. Die neuen Tests verwenden simulierte Windows-Fenster.

## Änderung in 0.2.0

- **Entwicklungszweige zusammengeführt:** Gmail-OAuth-API und Erweiterungsverwaltung bleiben aus dem umfangreicheren früheren Stand erhalten; verbesserte Fehlerbehandlung der Windows-Setup-/Build-Skripte wurde übernommen.
- **Autonomer Arbeitsmodus:** vorübergehende Ollama-Verbindungsfehler werden bis zu drei Versuche lang behandelt. Danach wird die Aufgabe **pausiert**, der Checkpoint bleibt erhalten.
- **Endlosschleifenbremse:** Drei identische Werkzeuganforderungen hintereinander pausieren die Aufgabe, statt dieselbe Aktion beliebig oft auszuführen.
- **Prüf-Nachweise:** eine erfolgreiche Syntaxprüfung für eine nicht vorhandene oder unbeteiligte Datei gilt nicht mehr als Nachweis für zuletzt bearbeiteten Code. Noch nicht validierte Dateien bleiben auch bei Wiederaufnahme im Checkpoint.
- **Freigaben:** abgelehnte Aktionen pausieren den Auftrag. Das UI lehnt unbeantwortete Freigabe-Dialoge nach einer Minute automatisch ab, statt unbegrenzt zu blockieren.
- **Diskretere Protokolle:** das Aktivitätenprotokoll zeichnet bei sensiblen Werkzeug-Argumenten nicht mehr den vollständigen Mail-/Texteingabeinhalt auf. Das lokale Gmail-Datenmodell ist unabhängig davon weiterhin vertraulich zu behandeln.
- **16 automatisierte Komponententests erfolgreich** unter Linux. GUI/EXE/Windows-Installer sowie echte lokale Modell-, Sprach- und Gmail-End-to-End-Tests sind **nicht** durchgeführt.

## Änderung in 0.1.1

- Aufgaben gelten nicht schon wegen einer KI-Antwort wie „Fertig“ als abgeschlossen; das Modell muss ein `complete_task`-Werkzeug aufrufen.
- Programmieraufgaben benötigen nach der **letzten** gespeicherten Änderung eine erfolgreich ausgeführte Test-/Syntaxprüfung. Ein früherer grüner Test reicht nicht aus.
- Bloße Dateiauflistungen und fehlgeschlagene Befehle werden nicht mehr als Arbeitsnachweis gezählt.
- Acht frühere automatisierte Komponententests unter Linux bestanden (Chat, Gedächtnis, Backups, Agent, Abschlusskontrolle, Gmail-Versandfreigabe).
- **Nicht getestet:** komplette Windows-Oberfläche, vollständige Sprachsteuerung, echte Gmail-Verbindung, Ollama-Modell auf i7-4770/RX 570, EXE/Installer.


## Auf Windows starten

1. Installiere **Python 3.11 oder neuer** und **Ollama**: https://www.python.org/downloads/windows/ und https://ollama.com/download/windows
2. PowerShell im entpackten Ordner öffnen. `powershell -ExecutionPolicy Bypass -File .\Setup_Windows.ps1` ausführen.
3. Ollama starten und `ollama pull qwen2.5-coder:7b` ausführen (falls nicht im Setup heruntergeladen).
4. `Start_SYTOX.bat` starten. In Einstellungen Modell / Projektordner anpassen.
5. Für die Erstellung einer eigenen Windows-EXE `Build_EXE.ps1` ausführen; optional `Windows_Installer.iss` mit Inno Setup kompilieren.

**Wichtig:** Der Download von Python/Ollama/Modellen und der Browser-Automation benötigt zunächst Internet. Danach laufen Modell und Chats lokal, aber Webseiten und Gmail brauchen selbstverständlich Internet. Die Anwendung wurde hier unter Linux statisch geprüft; die Windows-EXE und das Installationsskript wurden nicht auf einem Windows-PC getestet.

## Bereits im Quellcode vorhanden

- Qt-Desktop-Chat im schwarz/dunkelroten Stil, mehrere Chats, Chat-Umbenennung / Suche / Löschen.
- SQLite-Datenbank im Benutzerprofil mit Chat-Verlauf, Volltextabruf aus früheren Chats, expliziten Erinnerungen, Aufträgen und Audit-Protokoll.
- Ollama-Anbindung über dokumentierte Chat-API inklusive Werkzeuge; Modellname frei einstellbar.
- Agenten-Aufträge: einmalig, 1/3 Stunden, bis fertig, gesonderte Zeitangabe im Chat (z. B. „4 Stunden“), Status/Protokoll/Stop; gespeicherte Checkpoints und manuelles Wiederaufnehmen.
- Begrenzter Projektordner mit Dateien lesen/schreiben, Sicherung alter Dateien, Test-/Entwicklungsbefehle mit Freigabe bei ausführbarem Code.
- Internet: im Browser öffnen, separater automatisierter Chromium-Browser mit eigenem Login-Profil, Webseiten lesen/ausfüllen/klicken. **Jeder automatisierte Browser-Klick braucht Zustimmung** (damit nicht heimlich E-Mails gesendet werden).
- Windows-App-Suche, Fensterliste und Fensterauswahl, UI-Automation-Elemente sowie Text/Tastatur/Maus im explizit gewählten Fenster. Alle Aktionen mit Eingriff erfordern Freigabe. **Windows-Funktionalität nicht praktisch getestet.**
- Optionaler Gesprächsmodus mit lokalem Vosk-Wakeword „Hey Sytox“, Anschlussfragen ohne erneutes Aktivierungswort und optionalem freiem Zuhören (nicht auf Windows getestet).
- Lokale Sprachmemos und Offline-Transkription mit deutschem Vosk-Modell. Vorlesen über Windows SAPI/pyttsx3, Piper offline oder nach ausdrücklicher Zustimmung Edge Neural online.
- Self-Development-Ablauf mit getrennter Quellcodekopie, Original-Baseline, Diff, explizit freigegebener Syntax-/Unit-Testprüfung und ZIP-Kandidat zur manuellen Übernahme; kein Live-Update.

## Grenzen / noch nicht fertig

- **Nicht auf Windows end-to-end getestet.** Windows-Binärdatei und Inno-Installer müssen auf Windows gebaut und geprüft werden.
- Sprachmemo-Transkription braucht ein zusätzliches Vosk-Deutsch-Modell, z. B. von https://alphacephei.com/vosk/models; für natürlichere Stimmen Piper-Binary + geeignetes Stimmenmodell separat einrichten.
- Der Wakeword-Gesprächsmodus ist weiterhin experimentell und noch nicht praktisch auf Windows getestet. Die Spracheingabe pausiert während Antworten: keine echte simultane Unterhaltung; eine Sprachantwort per Stimme zu unterbrechen funktioniert dann nicht. Windows-TTS kann sich trotz Stopp-Knopf zu Ende abspielen. Bestehende TTS-Stimmen klingen je nach installierter Stimme möglicherweise noch robotisch.
- Gmail im bestehenden Chrome-Login nicht automatisch verbunden. Der Automationsbrowser hat ein eigenes Profil und benötigt die erste Anmeldung durch den Benutzer. Browser-Schritte sind nicht für Gmail durchgängig integriert/getestet.
- Selbstverbesserung arbeitet ausschließlich in einer Entwicklungs-Arbeitskopie. Getestete Updates werden nach Freigabe **nur als ZIP** bereitgestellt, nicht automatisch installiert. Tests sind keine Sicherheits-Sandbox.
- Die neue PC-Steuerung ist noch kein autonomes „Sehen“ des Bildschirms: sie liest Fenster-/Accessibility-Informationen, kann aber nicht jede grafische Anwendung zuverlässig bedienen. Programme mit Administratorrechten, Spielen mit eigener Oberfläche oder blockierter UI-Automation können scheitern.
- Kleine lokale Modelle können Tool-Aufrufe falsch einsetzen und Aufgaben falsch als erledigt bezeichnen. Es gibt keine Garantie, dass sie selbstständige Langzeit-Aufträge zuverlässig fertigstellen.
- Der Work-Loop benötigt einen laufenden PC, eine laufende App, verfügbare Ollama-Engine und ausreichend Speicher. Eine Zielzeit ist kein Versprechen für unterbrechungslose sinnvolle Arbeit: bei Abschluss/Blockaden stoppt die Aufgabe.
- Sicherheit: Auch genehmigte Befehle und ausführbare Testdateien können riskant sein. Projekte und ungetestete Software nur mit Backups ausführen.

## Datenschutz & Steuerung

Chats, Memories, Arbeitsprotokoll und Browser-Profil liegen standardmäßig unter `%APPDATA%\SytoxAssistant` (auf anderen Systemen `~/.local/share/SytoxAssistant`). Automatische Speicherung ist lokal; Webseitenzugriffe schicken Daten an die besuchten Server. Keine Telemetrie im Anwendungscode. Jeder vom Modell gestartete freie Befehl, PC-Klick und Browser-Klick muss freigegeben werden. Der Benutzer muss einer Fensterinspektion und dem Fokussieren ebenfalls zustimmen. Für unbeaufsichtigte Arbeit können deshalb Freigaben zur Blockade führen. Stoppen signalisiert die Beendigung und unterbricht laufende KI-Streaming-Antworten.

## Architektur

- `sytox/storage.py`: lokale SQLite-Speicherung und einfache Volltextsuche.
- `sytox/agent.py`: Ollama-API, Werkzeug-Agent und Auftragsschleife.
- `sytox/actions.py`: Werkzeuge, Berechtigungen, Backups, Browser, Selbstentwicklungskopie.
- `sytox/pc_control.py`: Windows-Fensterverwaltung, UI Automation und Unicode-Tastatureingaben.
- `sytox/selfdev.py`: getrennte Selbstentwicklungs-Worktree, Review, Tests und geprüfte ZIP-Kandidaten.
- `sytox/voice_features.py`: Aufnahme / Transkription / TTS.
- `sytox/ui.py`: PySide6-Oberfläche und Hintergrund-Worker.
- `tests/`: automatisierte Komponententests ohne Modell.

## Quellen

Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
Ollama Tool Calling: https://github.com/ollama/ollama/blob/main/docs/capabilities/tool-calling.mdx

## PC-Steuerung: Beispielablauf (in einer gestarteten Windows-Instanz)

1. „Finde Notepad“ → `pc_find_apps` liefert lokale Verknüpfungen mit Pfaden.
2. „Starte Notepad“ → `pc_open_app` fragt vor Ausführung nach Zustimmung.
3. `pc_list_windows` liefert Fenster-IDs; `pc_select_window` wählt nach Freigabe das Ziel.
4. Optional `pc_inspect_window`, um Edit-/Button-Elemente zu entdecken (Freigabe erforderlich).
5. `pc_type_text`/`pc_hotkey` oder `pc_click_control` steuern nur dieses Fenster, jeweils nach Zustimmung.
6. Bei geschlossenem, verdecktem oder verändertem Fenster wird die Aktion mit einer Fehlermeldung beendet.

Für fortgeschrittene, unbeaufsichtigte Nutzung reicht diese Version noch nicht: Jede Interaktion erfordert Freigaben. Das absichtliche Sicherheitsmodell verhindert unbeaufsichtigte Änderungen an anderen Apps; später könnten eng begrenzte, vom Benutzer vorab freigegebene Aufgabenprofile hinzukommen.

**Manueller Windows-Test vor Freigabe der Anwendung:** Setup_Windows.ps1 im Testsystem ausführen; `python -m unittest discover -s tests` testen; dann mit einem leeren Notepad-Fenster App-Suche, Auswahl, Eingabe mit „äöüß“, Fensterwechsel und Klickgrenzen prüfen. Keine echten Zugangsdaten oder produktiven Dateien für diese Tests verwenden.

## Änderung 0.2.7 (Windows-Installer-Stabilität)
- Der isolierte Installations-Smoke-Test hat verbindliche Laufzeitgrenzen:
  Installation 180 s, GUI-Start 45 s, Deinstallation 120 s.
- Bei einem Zeitlimit wird der hängende Prozessbaum beendet und die CI meldet einen Fehler,
  statt unbegrenzt auf einen fehlerhaften Windows-Start zu warten.
- Startfehlerprotokolle der installierten Anwendung werden im fehlgeschlagenen Test ausgegeben.
- Das ist **kein** unter Windows ausgeführter Testlauf: Der echte Inno-/Windows-Test benötigt
  weiterhin einen Windows-Runner. Auch die Windows-EXE liegt diesem Quellpaket nicht bei.


### SYTOX Auto-Update (ab 0.3.3)

- **Automatische Versionssuche:** Beim Start fragt die App GitHub Releases nach einer neueren stabilen Version ab (im Menü *Einstellungen* abschaltbar). Über *Nach Updates suchen* in der linken Leiste lässt sich die Prüfung jederzeit manuell starten.
- **Keine stille Installation:** Der Download und das Starten des Installers erfordern jeweils eine ausdrückliche Bestätigung. Laufende Agent-Aufträge werden nicht automatisch beendet.
- **Geprüfte Dateien:** Nur der offizielle Installer `SYTOX_Assistant_Setup_<version>.exe` aus dem GitHub-Release mit gleichnamiger `.sha256`-Datei wird akzeptiert. Stimmt der SHA-256-Hash nicht, wird die heruntergeladene Datei verworfen.
- **Erst App schließen, dann installieren:** Der gestartete Update-Helfer wartet auf das Ende der bisherigen SYTOX-Instanz und öffnet anschließend Inno Setup. Chatverlauf und Einstellungen liegen separat unter `%APPDATA%\SytoxAssistant` und werden nicht überschrieben.
- **Windows-Installer erforderlich:** Die Installation funktioniert mit der regulär installierten Windows-EXE. Beim Betrieb aus Python/Quellcode wird nur auf das verfügbare Release hingewiesen.
- **Releases veröffentlichen:** Eine Version muss in `sytox/__init__.py`, `Windows_Installer.iss` und den zugehörigen Release-Skripten identisch sein. Ein Git-Tag wie `v0.3.3` löst `.github/workflows/windows-release.yml` aus: Tests → Windows-EXE → Installer → Installations-Smoketest → Release mit Installer und SHA-256-Datei. **CI-Artefakte allein sind keine automatischen Updates.** Solange kein GitHub Release veröffentlicht wurde, meldet SYTOX keine neue Version.

Hinweis: Ein SHA-256-Hash erkennt einen beschädigten oder geänderten Download gegenüber der veröffentlichten Datei, ersetzt aber keine Code-Signatur des Herausgebers.
