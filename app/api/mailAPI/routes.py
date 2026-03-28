import logging
import os
import base64
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import json
import sqlite3
from app.models.complaint_manager import Base, Complaint
from app.db.database import engine, Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.api.mailAPI.crud import upsert_in_complaint, get_complaints
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=['Mail API'])
load_dotenv()

SCOPES = os.getenv('SCOPES')
TOKEN_PATH = os.getenv('TOKEN_PATH')
CREDENTIALS_PATH = os.getenv('CREDENTIALS_PATH')
FETCH_STATE_FILE = "last_fetch_state.json"

def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
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

def get_last_fetch_date() -> str | None:
      """Read last fetch date from state file. Returns None if never fetched."""
      if not os.path.exists(FETCH_STATE_FILE):
          return None
      with open(FETCH_STATE_FILE, "r") as f:
          data = json.load(f)
      return data.get("last_fetch_date") 

def set_last_fetch_date(date: str = None) -> str:
      """Write current datetime as last fetch date. Returns the date written."""
      if date is None:
          date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
      with open(FETCH_STATE_FILE, "w") as f:
          json.dump({"last_fetch_date": date}, f)
      return date


@router.get("/read_mails_by_date")
async def read_mails_by_date(
    max_results: int = 50
):
    """
    Read emails within a date range.
    - from_date: Start date (YYYY/MM/DD format, e.g., '2026/01/01')
    - to_date: End date (YYYY/MM/DD format, e.g., '2026/03/28')
    - max_results: Number of emails to retrieve (default: 50)
    """
    try:
        from_date = get_last_fetch_date()
        logger.info(f'----From Date : {from_date}----')
        if from_date is None:
            return {
                "status": "info",
                  "message": "No prior fetch found. Set an initial date using /init_fetch first.",
                  "data": [],
                  "count": 0
            }
        from_date_gmail = from_date.split(" ")[0].replace("-", "/")
        
        to_date_gmail = (datetime.now() + timedelta(days=1)).strftime("%Y/%m/%d")
        query = f"after:{from_date_gmail} before:{to_date_gmail}"
        logger.info(f'----Query : {query}----')
        service = get_gmail_service()
        logger.info(f'----Connected to Gmail Services----')
        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q=query
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            set_last_fetch_date(now)
            return {
                "status": "success",
                "data": [],
                "count": 0,
                "from_date": from_date,
                "to_date": now
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
        logger.info(f'----Extracted Email----')
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        set_last_fetch_date(now)

        # Upsert in complaint table
        engine = create_engine("sqlite:///app\db\complaint_manager.db")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        upsert_in_complaint(session, emails)
        return {
            "status": "success",
            "data": emails,
            "count": len(emails),
            "from_date": from_date,
            "to_date": now,
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
    
@router.post("/init_fetch")
async def init_fetch(from_date: str):
    """
    Initialize the last_fetch_date.
    Pass the date in YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format.
    Use this on first run to set how far back to fetch.
    """
    try:
        # Accept both formats
        parsed = datetime.strptime(from_date, "%Y-%m-%d")
        date_str = from_date + " 00:00:00"
        set_last_fetch_date(date_str)
        return {
            "status": "success",
            "message": f"Last fetch date initialized to {date_str}",
            "last_fetch_date": date_str
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

@router.get("/extract/complaint_manager database")
async def extract_db():
    engine = create_engine("sqlite:///app\db\complaint_manager.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    email_details = get_complaints(session)
    return {
        "email_details" : email_details
    }