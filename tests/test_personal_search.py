"""Personal context stays local unless the user asks for public research."""
import unittest
from unittest.mock import MagicMock, patch

from sytox.parallel_chat import ParallelReplyWorker
from sytox.web_search import should_search


class PersonalSearchPolicyTests(unittest.TestCase):
    def test_personal_context_is_not_a_public_search_query(self):
        questions = (
            'Welche Lieblingsfarbe habe ich?',
            'Wer bin ich?',
            'Was ist mein aktuelles Projekt?',
            'Welche Version habe ich auf meinem PC installiert?',
            'Welche Einstellungen nutze ich heute?',
            'Wo befindet sich mein Profil?',
            'Welche Daten sind in unserem Konto gespeichert?',
            'Was ist meine neueste Entscheidung zum Projekt?',
        )
        for question in questions:
            for local_first in (False, True):
                with self.subTest(question=question, local_first=local_first):
                    self.assertFalse(should_search(question, local_first=local_first))

    def test_machine_state_and_local_references_stay_local_without_possessives(self):
        for question in (
            'Welche Version ist auf diesem Computer installiert?',
            'Wer ist angemeldet?',
            'Was ist auf diesem PC installiert?',
            'Welche Dateien wurden geändert?',
            'Wo ist der Projektordner?',
            'Was ist in diesem Projekt aktuell offen?',
            'Welche Einstellungen verwendet das lokale Profil?',
        ):
            with self.subTest(question=question):
                self.assertFalse(should_search(question))
                self.assertFalse(should_search(question, local_first=True))

    def test_web_history_is_not_a_new_research_request(self):
        for question in (
            'Welche Google Apps habe ich genutzt?',
            'Welche Websuche habe ich gestern durchgeführt?',
            'Welche Themen habe ich recherchiert?',
            'Wann war ich zuletzt online?',
            'Welche Seiten habe ich im Internet besucht?',
        ):
            with self.subTest(question=question):
                self.assertFalse(should_search(question))

    def test_explicit_public_research_allows_possessive_context(self):
        for question in (
            'Suche im Internet nach Bibliotheken für mein Projekt.',
            'Bitte recherchiere aktuelle Preise für mein Smartphone.',
            'Kannst du für mein Projekt im Web nachschlagen?',
            'Bitte google meinen öffentlich bekannten Künstlernamen.',
            'Bitte online nachschlagen, welche Termine für mein Studium veröffentlicht sind.',
            'Was ist für mein Projekt verfügbar? Recherchiere im Internet.',
        ):
            for local_first in (False, True):
                with self.subTest(question=question, local_first=local_first):
                    self.assertTrue(should_search(question, local_first=local_first))

    def test_offline_request_wins_even_over_explicit_research(self):
        for question in (
            'Bitte google meine Firma offline.',
            'Recherchiere meinen Künstlernamen ohne Internet.',
            'Bitte suche nicht online nach meinem Profil.',
            'Was ist mein Projekt? Keine Websuche.',
        ):
            with self.subTest(question=question):
                self.assertFalse(should_search(question))

    def test_public_people_current_news_and_courtesy_requests_are_preserved(self):
        for question in (
            'Wer ist Jenna Ortega?',
            'Was sind die neuesten Nachrichten?',
            'Was ist GPT-6?',
            'Kannst du mir aktuelle Nachrichten geben?',
            'Kannst du mir sagen, was die neuesten Nachrichten sind?',
            'Suche im Internet nach aktuellen Nachrichten.',
        ):
            for local_first in (False, True):
                with self.subTest(question=question, local_first=local_first):
                    self.assertTrue(should_search(question, local_first=local_first))


class PersonalQuickChatSearchTests(unittest.TestCase):
    def test_personal_quick_questions_do_not_make_any_search_request(self):
        for question in ('Welche Lieblingsfarbe habe ich?',
                         'Was ist mein aktuelles Projekt?',
                         'Welche Einstellungen nutze ich heute?'):
            with self.subTest(question=question):
                worker = ParallelReplyWorker(
                    {'fast_model': 'qwen3:4b', 'ollama_url': 'http://localhost:11434'},
                    [{'role': 'user', 'content': question}], standalone=True,
                    memory_context='Die Lieblingsfarbe des Nutzers ist Dunkelrot.',
                )
                with patch('sytox.parallel_chat.OllamaClient') as client, \
                     patch('sytox.web_search.requests.get') as request:
                    client.return_value.chat.return_value = {'content': 'Dunkelrot.'}
                    worker.run()
                    request.assert_not_called()
                    messages = client.return_value.chat.call_args.args[0]
                    self.assertIn('Dunkelrot', messages[0]['content'])
                self.assertEqual(worker.outcome, 'done')

    def test_public_person_query_still_fetches_sources(self):
        worker = ParallelReplyWorker(
            {'fast_model': 'qwen3:4b', 'ollama_url': 'http://localhost:11434'},
            [{'role': 'user', 'content': 'Wer ist Jenna Ortega?'}], standalone=True,
        )
        xml = ('<rss><channel><item><title>Profil</title>'
               '<link>https://example.org/jenna</link>'
               '<description>Schauspielerin</description></item></channel></rss>')
        response = MagicMock()
        response.text, response.content = xml, xml.encode()
        with patch('sytox.parallel_chat.OllamaClient') as client, \
             patch('sytox.web_search.requests.get', return_value=response) as request:
            client.return_value.chat.return_value = {'content': 'Eine Schauspielerin.'}
            worker.run()
            request.assert_called_once()
            messages = client.return_value.chat.call_args.args[0]
            self.assertTrue(any('https://example.org/jenna' in m['content'] for m in messages))
        self.assertEqual(worker.outcome, 'done')


if __name__ == '__main__':
    unittest.main()
