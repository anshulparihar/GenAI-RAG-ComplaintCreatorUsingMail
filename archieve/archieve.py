#- -------------------Code to Read mail from gmail by claud--------------------

import logging
import os
import base64
from email import message_from_bytes
from typing import Optional

from fastapi import APIRouter, HTTPException
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=['Mail API'])

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = None

    # Check if token.json exists (stored credentials)
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # If no valid credentials, trigger OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(InstalledAppFlow)
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            # Save credentials for future use
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)

def parse_email_body(payload):
    """Extract body content from email payload."""
    body = None
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                if 'data' in part['body']:
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    break
            elif part['mimeType'] == 'text/html':
                if 'data' in part['body']:
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
    elif 'body' in payload and 'data' in payload['body']:
        body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')

    return body

def format_email_data(messages):
    """Format messages list to return readable email data."""
    formatted = []
    for msg in messages:
        email_data = {
            'id': msg['id'],
            'thread_id': msg.get('threadId', ''),
            'snippet': msg.get('snippet', '')
        }
        formatted.append(email_data)
    return formatted

@router.get("/read_mails")
async def read_mails(max_results: int = 10):
    """
    Read emails from Gmail inbox.

    Args:
        max_results: Maximum number of emails to retrieve (default: 10)

    Returns:
        List of emails with id, threadId, and snippet
    """
    try:
        service = get_gmail_service()

        # Get list of messages from inbox
        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q='in:inbox'
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            return {"status": "success", "data": [], "message": "No emails found"}

        # Get full details for each message
        detailed_emails = []
        for msg in messages:
            email = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            payload = email.get('payload', {})
            headers = payload.get('headers', [])

            # Extract email headers
            email_info = {
                'id': email['id'],
                'thread_id': email.get('threadId', ''),
                'snippet': email.get('snippet', ''),
                'from': next((h['value'] for h in headers if h['name'].lower() == 'from'), ''),
                'to': next((h['value'] for h in headers if h['name'].lower() == 'to'), ''),
                'subject': next((h['value'] for h in headers if h['name'].lower() == 'subject'), ''),
                'date': next((h['value'] for h in headers if h['name'].lower() == 'date'), ''),
                'body': parse_email_body(payload)
            }
            detailed_emails.append(email_info)

        return {
            "status": "success",
            "data": detailed_emails,
            "count": len(detailed_emails)
        }

    except FileNotFoundError as e:
        if 'credentials.json' in str(e):
            raise HTTPException(
                status_code=500,
                detail="credentials.json not found. Please download it from Google Cloud Console."
            )
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading emails: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search_emails")
async def search_emails(query: str, max_results: int = 10):
    """
    Search emails using Gmail search syntax.

    Args:
        query: Gmail search query (e.g., 'from:example@gmail.com', 'subject:urgent', 'is:unread')
        max_results: Maximum number of emails to retrieve

    Returns:
        List of matching emails
    """
    try:
        service = get_gmail_service()

        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q=query
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            return {"status": "success", "data": [], "message": "No emails found matching query"}

        detailed_emails = []
        for msg in messages:
            email = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            payload = email.get('payload', {})
            headers = payload.get('headers', [])

            email_info = {
                'id': email['id'],
                'thread_id': email.get('threadId', ''),
                'snippet': email.get('snippet', ''),
                'from': next((h['value'] for h in headers if h['name'].lower() == 'from'), ''),
                'subject': next((h['value'] for h in headers if h['name'].lower() == 'subject'), ''),
                'date': next((h['value'] for h in headers if h['name'].lower() == 'date'), ''),
                'body': parse_email_body(payload)
            }
            detailed_emails.append(email_info)

        return {
            "status": "success",
            "data": detailed_emails,
            "count": len(detailed_emails),
            "query": query
        }

    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="credentials.json not found. Please download it from Google Cloud Console."
        )
    except Exception as e:
        logger.error(f"Error searching emails: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
