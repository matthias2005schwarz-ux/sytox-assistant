"""Gmail REST integration via explicit user OAuth. Never reuse browser cookies/passwords."""
from __future__ import annotations

import base64
from email.message import EmailMessage
from email import policy
import json
import os
from pathlib import Path

import requests

from .storage import default_data_dir

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.send',
]
API = 'https://gmail.googleapis.com/gmail/v1/users/me'


class GmailError(RuntimeError):
    pass


class GmailClient:
    def __init__(self, secrets_file='', token_file=None):
        self.secrets_file = Path(secrets_file).expanduser() if secrets_file else None
        self.token_file = Path(token_file or default_data_dir() / 'gmail_oauth_token.json')

    def connect(self):
        """Opens official Google OAuth in browser; user logs in and grants permissions."""
        if not self.secrets_file or not self.secrets_file.is_file():
            raise GmailError('Zuerst eine Google-OAuth-Desktop-Client-JSON-Datei in den Einstellungen wählen.')
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GmailError('Google-OAuth-Paket fehlt. Setup_Windows.ps1 erneut ausführen.') from exc
        flow = InstalledAppFlow.from_client_secrets_file(str(self.secrets_file), scopes=SCOPES)
        credentials = flow.run_local_server(port=0, open_browser=True)
        self._save(credentials)
        return 'Gmail erfolgreich über Google autorisiert.'

    def _save(self, credentials):
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_file.with_suffix('.tmp')
        tmp.write_text(credentials.to_json(), encoding='utf-8')
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.token_file)

    def _credentials(self):
        if not self.token_file.is_file():
            raise GmailError('Gmail ist nicht verbunden. Bitte zuerst Gmail verbinden.')
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise GmailError('Google-OAuth-Bibliotheken fehlen.') from exc
        creds = Credentials.from_authorized_user_file(str(self.token_file), scopes=SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._save(creds)
            else:
                raise GmailError('Gmail-Freigabe abgelaufen. Bitte erneut verbinden.')
        return creds

    def connected(self):
        if not self.token_file.is_file():
            return False
        try:
            self._credentials()
            return True
        except Exception:
            return False

    def _request(self, method, endpoint, *, params=None, payload=None):
        creds = self._credentials()
        resp = requests.request(method, API + endpoint,
            headers={'Authorization': 'Bearer ' + creds.token,
                     'Accept': 'application/json'},
            params=params, json=payload, timeout=30)
        if not resp.ok:
            raise GmailError(f'Gmail API Fehler {resp.status_code}: {resp.text[:350]}')
        return resp.json()

    def search(self, query, limit=10):
        query = str(query).strip()[:400]
        if not query:
            raise GmailError('Suchtext fehlt.')
        limit = min(max(int(limit), 1), 20)
        data = self._request('GET', '/messages', params={'q': query, 'maxResults': limit})
        # Message IDs alone aren't personal details, but the assistant may call read for context.
        return {'message_ids': [m['id'] for m in data.get('messages', []) if m.get('id')],
                'estimated_total': data.get('resultSizeEstimate', 0)}

    @staticmethod
    def _body(payload):
        if not isinstance(payload, dict):
            return ''
        if payload.get('mimeType', '').startswith('text/plain') and payload.get('body', {}).get('data'):
            encoded = payload['body']['data']
            return base64.urlsafe_b64decode(encoded + '===').decode('utf-8', errors='replace')
        for part in payload.get('parts', []):
            result = GmailClient._body(part)
            if result:
                return result
        return ''

    def read(self, message_id):
        if not isinstance(message_id, str) or len(message_id) > 80 or not message_id.isalnum():
            raise GmailError('Ungültige Gmail-Nachrichten-ID.')
        msg = self._request('GET', '/messages/' + message_id, params={'format': 'full'})
        headers = {h.get('name','').lower(): h.get('value','') for h in msg.get('payload', {}).get('headers', [])}
        return {'id': msg.get('id'), 'from': headers.get('from', ''), 'to': headers.get('to', ''),
                'subject': headers.get('subject', ''), 'date': headers.get('date', ''),
                'snippet': msg.get('snippet', '')[:1000],
                'text': self._body(msg.get('payload', {}))[:16000]}

    @staticmethod
    def _email(to, subject, body):
        to = str(to).strip()
        if not to or '\n' in to or '\r' in to or '@' not in to or len(to) > 320:
            raise GmailError('Ungültiger Empfänger.')
        if not isinstance(subject, str) or '\n' in subject or '\r' in subject:
            raise GmailError('Ungültiger Betreff.')
        if not isinstance(body, str) or len(body) > 100000:
            raise GmailError('Nachricht zu lang oder ungültig.')
        message = EmailMessage(policy=policy.SMTP)
        message['To'] = to
        message['Subject'] = subject[:800]
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')

    def draft(self, to, subject, body):
        raw = self._email(to, subject, body)
        result = self._request('POST', '/drafts', payload={'message': {'raw': raw}})
        return {'draft_id': result.get('id'), 'status': 'Entwurf erstellt – nicht versendet'}

    def send(self, to, subject, body):
        raw = self._email(to, subject, body)
        result = self._request('POST', '/messages/send', payload={'raw': raw})
        return {'message_id': result.get('id'), 'status': 'Von Gmail als versendet gemeldet'}
