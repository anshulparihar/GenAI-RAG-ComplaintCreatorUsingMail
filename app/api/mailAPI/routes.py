import logging
import os
import base64
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=['Mail API'])
load_dotenv()

SCOPES = os.getenv('SCOPES')
TOKEN_PATH = os.getenv('TOKEN_PATH')
CREDENTIALS_PATH = os.getenv('CREDENTIALS_PATH')


def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(InstalledAppFlow())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def parse_email_body(payload: dict) -> Optional[str]:
    """Extract body from email payload."""
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain' and 'body' in part and 'data' in part['body']:
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            if part['mimeType'] == 'text/html' and 'body' in part and 'data' in part['body']:
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
    elif 'body' in payload and 'data' in payload['body']:
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
    return None


def extract_headers(headers: list, name: str) -> str:
    """Extract header value by name (case-insensitive)."""
    return next((h['value'] for h in headers if h['name'].lower() == name.lower()), '')


@router.get("/read_mails")
async def read_mails(max_results: int = 10):
    """
    Read emails from Gmail inbox.
    - max_results: Number of emails to retrieve (default: 10)
    """
    try:
        service = get_gmail_service()

        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q='in:inbox'
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            return {"status": "success", "data": [], "count": 0}

        emails = []
        for msg in messages:
            email = service.users().messages().get(
                userId='me', id=msg['id'], format='full'
            ).execute()

            payload = email.get('payload', {})
            headers = payload.get('headers', [])

            emails.append({
                'id': email['id'],
                'thread_id': email.get('threadId', ''),
                'snippet': email.get('snippet', ''),
                'from': extract_headers(headers, 'from'),
                'to': extract_headers(headers, 'to'),
                'subject': extract_headers(headers, 'subject'),
                'date': extract_headers(headers, 'date'),
                'body': parse_email_body(payload)
            })

        return {"status": "success", ""
                "data": emails, 
                "count": len(emails),
                "results":results}

    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"{CREDENTIALS_PATH} not found. Download from Google Cloud Console."
        )
    except Exception as e:
        logger.error(f"Error reading emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search_emails")
async def search_emails(query: str, max_results: int = 10):
    """
    Search emails using Gmail search syntax.
    - query: Gmail query (e.g., 'from:user@gmail.com', 'subject:urgent is:unread')
    - max_results: Number of results (default: 10)
    """
    try:
        service = get_gmail_service()

        results = service.users().messages().list(
            userId='me', maxResults=max_results, q=query
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            return {"status": "success", "data": [], "count": 0, "query": query}

        emails = []
        for msg in messages:
            email = service.users().messages().get(
                userId='me', id=msg['id'], format='full'
            ).execute()

            payload = email.get('payload', {})
            headers = payload.get('headers', [])

            emails.append({
                'id': email['id'],
                'thread_id': email.get('threadId', ''),
                'snippet': email.get('snippet', ''),
                'from': extract_headers(headers, 'from'),
                'subject': extract_headers(headers, 'subject'),
                'date': extract_headers(headers, 'date'),
                'body': parse_email_body(payload)
            })

        return {"status": "success", "data": emails, "count": len(emails), "query": query}

    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"{CREDENTIALS_PATH} not found. Download from Google Cloud Console."
        )
    except Exception as e:
        logger.error(f"Error searching emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/read_mails_by_date")
async def read_mails_by_date(
    from_date: str,
    to_date: str,
    max_results: int = 50
):
    """
    Read emails within a date range.
    - from_date: Start date (YYYY/MM/DD format, e.g., '2026/01/01')
    - to_date: End date (YYYY/MM/DD format, e.g., '2026/03/28')
    - max_results: Number of emails to retrieve (default: 50)
    """
    try:
        query = f"after:{from_date} before:{to_date}"
        service = get_gmail_service()

        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q=query
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            return {
                "status": "success",
                "data": [],
                "count": 0,
                "from_date": from_date,
                "to_date": to_date
            }

        emails = []
        for msg in messages:
            email = service.users().messages().get(
                userId='me', id=msg['id'], format='full'
            ).execute()

            payload = email.get('payload', {})
            headers = payload.get('headers', [])

            emails.append({
                'id': email['id'],
                'thread_id': email.get('threadId', ''),
                'snippet': email.get('snippet', ''),
                'from': extract_headers(headers, 'from'),
                'to': extract_headers(headers, 'to'),
                'subject': extract_headers(headers, 'subject'),
                'date': extract_headers(headers, 'date'),
                'body': parse_email_body(payload)
            })

        return {
            "status": "success",
            "data": emails,
            "count": len(emails),
            "from_date": from_date,
            "to_date": to_date,
            "messages":messages,
            "results" : results
        }

    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"{CREDENTIALS_PATH} not found. Download from Google Cloud Console."
        )
    except Exception as e:
        logger.error(f"Error reading emails by date: {e}")
        raise HTTPException(status_code=500, detail=str(e))