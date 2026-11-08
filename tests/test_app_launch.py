"""Direct app requests are resolved as data without touching a real desktop."""
import unittest

from sytox.app_launch import app_open_intent, resolve_app_request


class FakeDesktop:
    def __init__(self, *, windows=(), apps=(), window_error=None, app_error=None):
        self.app_windows = list(windows)
        self.apps = list(apps)
        self.window_error = window_error
        self.app_error = app_error
        self.calls = []

    def find_app_windows(self, query):
        self.calls.append(('find_app_windows', query))
        if self.window_error:
            raise self.window_error
        return self.app_windows

    def find_apps(self, query):
        self.calls.append(('find_apps', query))
        if self.app_error:
            raise self.app_error
        return self.apps

    def windows(self):
        raise AssertionError('Raw window titles must never identify an application.')

    def open_app(self, _path):
        raise AssertionError('A resolver must never start a program.')

    def activate(self, _window_id):
        raise AssertionError('A resolver must never switch focus.')


def shortcut(name='Spotify', path='C:/Users/Test/Desktop/Spotify.lnk'):
    return {'name': name, 'path': path}


def app_window(window_id=42, title='Song - Artist', app_name='Spotify'):
    return {'id': window_id, 'title': title, 'app_name': app_name,
            'executable': f'C:/Programs/{app_name}/{app_name}.exe'}


class DirectAppIntentTests(unittest.TestCase):
    def test_direct_commands_need_no_program_keyword_or_model(self):
        for phrase, expected in (
                ('öffne Spotify', 'Spotify'),
                ('starte bitte Discord', 'Discord'),
                ('öffne das Programm Spotify', 'Spotify'),
                ('bitte öffne Google Chrome', 'Google Chrome'),
                ('Hey Sytox, öffne Spotify.', 'Spotify'),
                ('Öffne bitte Spotify!', 'Spotify')):
            with self.subTest(phrase=phrase):
                self.assertEqual(app_open_intent(phrase), expected)

    def test_natural_polite_requests_use_direct_launcher(self):
        for phrase, expected in (
                ('Kannst du Spotify öffnen?', 'Spotify'),
                ('Hey Sytox, kannst du bitte Spotify öffnen?', 'Spotify'),
                ('Könntest du Discord starten?', 'Discord'),
                ('Würdest du bitte Notepad öffnen?', 'Notepad'),
                ('Could you please open Spotify?', 'Spotify'),
                ('Open Google Chrome', 'Google Chrome')):
            with self.subTest(phrase=phrase):
                self.assertEqual(app_open_intent(phrase), expected)

    def test_polite_requests_still_reject_unsafe_actions(self):
        for phrase in ('Kannst du Spotify öffnen und Discord starten?',
                       'Kannst du nicht Spotify öffnen?',
                       'Kannst du Spotify.exe öffnen?',
                       'Kannst du Spotify öffnen? und danach löschen',
                       'Kannst du die Datei öffnen?',
                       'Wie kann ich Spotify öffnen?',
                       'Kannst du Spotify öffnen??'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(app_open_intent(phrase))

    def test_curated_aliases_do_not_guess_at_unrelated_names(self):
        for phrase, expected in (('starte Taschenrechner', 'Rechner'),
                                 ('öffne Chrome', 'Google Chrome'),
                                 ('öffne Notepad', 'Notepad'),
                                 ('öffne Meine Musik App', 'Meine Musik App')):
            with self.subTest(phrase=phrase):
                self.assertEqual(app_open_intent(phrase), expected)

    def test_search_questions_negation_and_quoted_commands_are_not_launch_intents(self):
        for phrase in ('suche Programm Firefox', 'finde Spotify',
                       'Wie öffne ich Spotify?',
                       'öffne Spotify nicht', 'öffne nicht Spotify',
                       'Bitte starte kein Spotify', '"öffne Spotify"',
                       'Erkläre den Befehl öffne Spotify', 'öffne die private Datei',
                       'öffne PC-Steuerung', 'öffne Windows-Steuerung'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(app_open_intent(phrase))

    def test_paths_urls_arguments_and_chained_actions_stay_out_of_fast_path(self):
        for phrase in ('öffne https://example.org', 'öffne C:\\Windows\\notepad.exe',
                       'öffne ../Spotify', 'öffne spotify.exe', 'öffne Spotify --help',
                       'öffne Spotify; starte Discord', 'öffne Spotify und Discord',
                       'öffne Spotify und lösche eine Datei', 'öffne Spotify starte Discord', 'öffne $(calc)',
                       'öffne `Spotify`', 'öffne "Spotify"', 'öffne Spotify\nstarte Discord',
                       'öffne A', 'öffne das Programm', 'öffne bitte', 'öffne ' + 'A' * 81, '', None):
            with self.subTest(phrase=phrase):
                self.assertIsNone(app_open_intent(phrase))


class AppRequestResolutionTests(unittest.TestCase):
    def test_notepad_plus_plus_remains_a_distinct_requested_program(self):
        self.assertEqual(app_open_intent('Öffne Notepad++'), 'Notepad++')
        desktop = FakeDesktop(apps=[shortcut('Notepad', 'C:/Apps/Notepad.lnk'),
                                    shortcut('Notepad++', 'C:/Apps/NotepadPlusPlus.lnk')])
        result = resolve_app_request(desktop, 'Notepad++')
        self.assertEqual(result['status'], 'single')
        self.assertEqual(result['candidates'][0]['name'], 'Notepad++')
        self.assertEqual(desktop.calls[0], ('find_app_windows', 'Notepad++'))

    def test_existing_process_window_is_preferred_without_starting_a_second_copy(self):
        desktop = FakeDesktop(windows=[app_window()], apps=[shortcut()])
        result = resolve_app_request(desktop, 'Spotify')
        self.assertEqual(result['status'], 'single')
        self.assertEqual(result['query'], 'Spotify')
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['kind'], 'window')
        self.assertEqual(result['candidates'][0]['window_id'], 42)
        self.assertEqual(desktop.calls, [('find_app_windows', 'Spotify')])

    def test_multiple_running_windows_require_a_choice_even_if_one_is_active(self):
        first = app_window(11, 'Erstes Dokument', 'Notepad')
        first['active'] = True
        desktop = FakeDesktop(windows=[first, app_window(12, 'Zweites Dokument', 'Notepad')])
        result = resolve_app_request(desktop, 'Notepad')
        self.assertEqual(result['status'], 'multiple')
        self.assertEqual({entry['window_id'] for entry in result['candidates']}, {11, 12})
        self.assertTrue(all(entry['kind'] == 'window' for entry in result['candidates']))
        self.assertNotIn('find_apps', [call[0] for call in desktop.calls])

    def test_a_browser_tab_title_is_not_used_as_spotify_identity(self):
        # find_app_windows has already checked process identity and found no
        # Spotify window. A raw browser title must never override that answer.
        desktop = FakeDesktop(apps=[shortcut()])
        result = resolve_app_request(desktop, 'Spotify')
        self.assertEqual(result['status'], 'single')
        self.assertEqual(result['candidates'][0]['kind'], 'app')
        self.assertEqual([call[0] for call in desktop.calls], ['find_app_windows', 'find_apps'])

    def test_exact_shortcut_wins_over_partial_names_and_maintenance_entries(self):
        desktop = FakeDesktop(apps=[shortcut('Spotify Web Player', 'C:/Apps/Web.lnk'),
                                    shortcut('Spotify deinstallieren', 'C:/Apps/Uninstall.lnk'),
                                    shortcut(), shortcut('Spotify Updater', 'C:/Apps/Updater.lnk')])
        result = resolve_app_request(desktop, 'Spotify')
        self.assertEqual(result['status'], 'single')
        self.assertEqual([entry['name'] for entry in result['candidates']], ['Spotify'])

    def test_distinct_exact_shortcut_paths_are_not_silently_merged(self):
        desktop = FakeDesktop(apps=[shortcut(path='C:/Users/Test/Desktop/Spotify.lnk'),
                                    shortcut(path='C:/ProgramData/Spotify.lnk')])
        result = resolve_app_request(desktop, 'Spotify')
        self.assertEqual(result['status'], 'multiple')
        self.assertEqual(len(result['candidates']), 2)

    def test_same_shortcut_path_is_deduplicated_case_insensitively(self):
        desktop = FakeDesktop(apps=[shortcut(path='C:/Users/Test/Desktop/Spotify.lnk'),
                                    shortcut(path='c:/users/test/desktop/SPOTIFY.LNK')])
        result = resolve_app_request(desktop, 'Spotify')
        self.assertEqual(result['status'], 'single')
        self.assertEqual(len(result['candidates']), 1)

    def test_ambiguous_partial_matches_remain_an_explicit_choice(self):
        desktop = FakeDesktop(apps=[shortcut('Spotify Desktop', 'C:/Apps/One.lnk'),
                                    shortcut('Spotify Music', 'C:/Apps/Two.lnk')])
        result = resolve_app_request(desktop, 'Spotify')
        self.assertEqual(result['status'], 'multiple')
        self.assertEqual(len(result['candidates']), 2)

    def test_a_single_partial_name_can_be_confirmed_without_guessing_another_app(self):
        result = resolve_app_request(FakeDesktop(apps=[shortcut('Spotify Desktop')]), 'Spotify')
        self.assertEqual(result['status'], 'single')
        self.assertEqual(result['candidates'][0]['kind'], 'app')
        self.assertEqual(result['candidates'][0]['name'], 'Spotify Desktop')

    def test_missing_program_or_only_maintenance_shortcuts_explains_no_match(self):
        for apps in ([], [shortcut('Spotify deinstallieren', 'C:/Apps/Uninstall.lnk'),
                          shortcut('Spotify Updater', 'C:/Apps/Updater.lnk')],
                     [shortcut('Discord', 'C:/Apps/Discord.lnk')]):
            with self.subTest(apps=apps):
                result = resolve_app_request(FakeDesktop(apps=apps), 'Spotify')
                self.assertEqual(result['status'], 'not_found')
                self.assertEqual(result['candidates'], [])
                self.assertTrue(result['message'].strip())

    def test_compact_maintenance_names_cannot_replace_the_requested_program(self):
        for name in ('SpotifyUpdater', 'SpotifySetup', 'SpotifyUninstall',
                     'spotifyupdater', 'SpotifyInstall', 'SpotifyUpdateService'):
            with self.subTest(name=name):
                desktop = FakeDesktop(apps=[shortcut(name, 'C:/Apps/' + name + '.lnk')])
                result = resolve_app_request(desktop, 'Spotify')
                self.assertEqual(result['status'], 'not_found')
                self.assertEqual(result['candidates'], [])

    def test_curated_alias_fallback_is_explicit_and_unknown_queries_are_bounded(self):
        class LocalizedDesktop(FakeDesktop):
            def find_apps(self, query):
                self.calls.append(('find_apps', query))
                return [shortcut('Chrome', 'C:/Apps/Chrome.lnk')] if query == 'Chrome' else []

        desktop = LocalizedDesktop()
        result = resolve_app_request(desktop, 'Google Chrome')
        self.assertEqual(result['status'], 'single')
        self.assertEqual(result['candidates'][0]['name'], 'Chrome')
        self.assertEqual(desktop.calls, [('find_app_windows', 'Google Chrome'),
                                         ('find_apps', 'Google Chrome'), ('find_apps', 'Chrome')])
        unknown = FakeDesktop()
        self.assertEqual(resolve_app_request(unknown, 'Unbekannt')['status'], 'not_found')
        self.assertEqual(len(unknown.calls), 2)

    def test_exact_alias_match_wins_over_a_primary_canary_partial(self):
        class ChromeDesktop(FakeDesktop):
            def find_apps(self, query):
                self.calls.append(('find_apps', query))
                return ([shortcut('Google Chrome Canary', 'C:/Apps/Canary.lnk')]
                        if query == 'Google Chrome' else [shortcut('Chrome', 'C:/Apps/Chrome.lnk')])

        desktop = ChromeDesktop()
        result = resolve_app_request(desktop, 'Chrome')
        self.assertEqual(result['status'], 'single')
        self.assertEqual(result['candidates'], [{'kind': 'app', 'name': 'Chrome', 'path': 'C:/Apps/Chrome.lnk'}])
        self.assertEqual(len(desktop.calls), 3)

    def test_distinct_exact_alias_paths_remain_a_choice_with_shared_path_dedup(self):
        class ChromeDesktop(FakeDesktop):
            def find_apps(self, query):
                self.calls.append(('find_apps', query))
                if query == 'Google Chrome':
                    return [shortcut('Google Chrome', 'C:/System/Chrome.lnk')]
                return [shortcut('Chrome', 'c:/system/CHROME.LNK'),
                        shortcut('Chrome', 'C:/Users/Test/Chrome.lnk')]

        desktop = ChromeDesktop()
        result = resolve_app_request(desktop, 'Chrome')
        self.assertEqual(result['status'], 'multiple')
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual({entry['path'] for entry in result['candidates']},
                         {'C:/System/Chrome.lnk', 'C:/Users/Test/Chrome.lnk'})
        self.assertEqual(len(desktop.calls), 3)

    def test_invalid_backend_entries_cannot_become_launch_candidates(self):
        desktop = FakeDesktop(windows=[None, {}, {'id': True}, {'id': -1}],
                              apps=[None, {}, {'name': 'Spotify'},
                                    shortcut(path='https://example.org/Spotify.lnk'),
                                    shortcut(path='C:/Apps/Spotify.txt')])
        result = resolve_app_request(desktop, 'Spotify')
        self.assertEqual(result['status'], 'not_found')
        self.assertEqual(result['candidates'], [])

    def test_discovery_errors_are_reported_without_turning_into_a_launch_or_ai_request(self):
        for desktop in (FakeDesktop(window_error=OSError('Windows nicht verfügbar')),
                        FakeDesktop(app_error=PermissionError('Zugriff verweigert'))):
            with self.subTest(desktop=desktop):
                result = resolve_app_request(desktop, 'Spotify')
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['candidates'], [])
                self.assertTrue(result['message'].strip())


if __name__ == '__main__':
    unittest.main()
