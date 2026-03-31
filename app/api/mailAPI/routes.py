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
from app.models.complaint_manager import Base, Complaint, PendingEmail
from app.db.database import engine, Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.api.mailAPI.crud import (
    upsert_in_complaint, get_complaints, get_complaint_by_id, update_complaint,
    upsert_pending_email, get_pending_emails, get_all_pending_emails,
    get_pending_email_by_id, mark_pending_email_reviewed,
    create_complaint_from_pending, bulk_create_complaints_from_pending,
    create_manual_complaint
)
from app.agents.complaint_summary_agent import classify_email
from app.agents.vector_store import store_in_chromadb, upsert_in_chromadb, retrieve_complaints

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

        # Upsert in pending_emails table (ALL emails, no auto-complaint creation)
        engine = create_engine("sqlite:///app\db\complaint_manager.db")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        classification_output = []
        for email in emails:
            email_id = email.get('id', '')
            sender = email.get('from','')
            subject = email.get('subject','')
            body = email.get('body','')
            email_date = email.get('date','')

            # Classify
            logger.info(f'----Starting Classification----')
            classification = classify_email(email_id, sender, subject, body, email_date)
            classification_output.append(classification)

            # Store ALL emails in pending_emails (awaiting user review)
            upsert_pending_email(session, email, classification)

            # Store ALL emails in ChromaDB (email_id as ChromaDB ID)
            text_to_embed = f"{subject}\n{body if body else ''}"
            chroma_metadata = {
                "sender": sender,
                "subject": subject,
                "email_date": email_date,
                "category": classification.get("category", ""),
                "severity": classification.get("severity", ""),
                "department": classification.get("department", ""),
                "product": classification.get("product", ""),
                "email_id": email_id,
                "complaint_id": None,  # Will be updated when complaint is created
                "is_complaint": classification.get("is_complaint", "0"),
            }
            store_in_chromadb(email_id, text_to_embed, chroma_metadata)

        session.close()

        return {
            "status": "success",
            "data": emails,
            "from_date": from_date,
            "to_date": now,
            "classification_output": classification_output
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


@router.get("/debug/chroma")
async def debug_chroma():
    from app.agents.vector_store import collection
    results = collection.get()
    return {
        "count": collection.count(),
        "ids": results["ids"],
        "metadatas": results["metadatas"],
        "collection" : results['documents'],
        "results" : results
    }

@router.get("/complaints/{complaint_id}")
async def get_complaint(complaint_id: str):
    """Fetch a single complaint by its complaint_id."""
    engine = create_engine("sqlite:///app\db\complaint_manager.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    complaint = get_complaint_by_id(session, complaint_id)
    session.close()

    if not complaint:
        raise HTTPException(status_code=404, detail=f"Complaint {complaint_id} not found")

    return {
        "status": "success",
        "complaint": {
            "complaint_id": complaint.complaint_id,
            "email_id": complaint.email_id,
            "email_date": complaint.email_date,
            "sender": complaint.sender,
            "subject": complaint.subject,
            "body_snippet": complaint.body_snippet,
            "is_complaint": complaint.is_complaint,
            "category": complaint.category,
            "sub_category": complaint.sub_category,
            "severity": complaint.severity,
            "department": complaint.department,
            "product": complaint.product,
            "batch_number": complaint.batch_number,
            "shift": complaint.shift,
            "status": complaint.status,
            "reviewed_by": complaint.reviewed_by,
            "reviewed_at": complaint.reviewed_at,
            "resolution": complaint.resolution,
            "chroma_id": complaint.chroma_id,
            "created_at": complaint.created_at,
            "updated_at": complaint.updated_at,
        }
    }

@router.put("/complaints/{complaint_id}")
async def update_complaint_fields(complaint_id: str, updates: dict):
    """
    Update complaint fields. Updates both SQLite and ChromaDB.
    Any fields passed in the body will replace the existing values.
    """
    engine = create_engine("sqlite:///app\db\complaint_manager.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    complaint = update_complaint(session, complaint_id, updates)
    session.close()

    if not complaint:
        raise HTTPException(status_code=404, detail=f"Complaint {complaint_id} not found")

    # Update ChromaDB — delete old entry and re-add with new metadata
    chroma_id = complaint.chroma_id or complaint.complaint_id
    text_to_embed = f"{complaint.subject}\n{complaint.body_snippet or ''}"
    chroma_metadata = {
        "sender": complaint.sender or "",
        "subject": complaint.subject or "",
        "email_date": complaint.email_date or "",
        "category": complaint.category or "",
        "severity": complaint.severity or "",
        "department": complaint.department or "",
        "product": complaint.product or "",
        "email_id": complaint.email_id or "",
        "complaint_id": complaint.complaint_id or "",
    }
    upsert_in_chromadb(complaint.email_id, text_to_embed, chroma_metadata)

    return {
        "status": "success",
        "message": f"Complaint {complaint_id} updated",
        "complaint_id": complaint.complaint_id
    }

@router.get("/retrieve")
async def query_retrieval(query):
    # 1. Retrieve from ChromaDB
    results = retrieve_complaints(query, 10)

    # 2. Format context from results (ALL emails, with or without complaints)
    contexts = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]

    for i, email_id in enumerate(ids):
        meta = metas[i] if i < len(metas) else {}
        doc = docs[i] if i < len(docs) else ""
        complaint_id = meta.get("complaint_id")
        is_complaint = meta.get("is_complaint", "0")

        context_entry = (
            f"Email ID: {email_id}\n"
            f"Subject: {meta.get('subject', 'N/A')}\n"
            f"From: {meta.get('sender', 'N/A')}\n"
            f"Date: {meta.get('email_date', 'N/A')}\n"
            f"LLM Classification: {meta.get('category', 'N/A')} | Severity: {meta.get('severity', 'N/A')}\n"
            f"Department: {meta.get('department', 'N/A')} | Product: {meta.get('product', 'N/A')}\n"
            f"Complaint Registered: {'Yes - Complaint ID: ' + str(complaint_id) if complaint_id and str(complaint_id) != 'None' else 'No'}\n"
            f"Email Content: {doc[:800]}..."
        )
        contexts.append(context_entry)

    context_str = "\n\n---\n\n".join(contexts) if contexts else "No relevant emails found."

    # 3. Read chat prompt
    prompt_template = """You are a helpful assistant for Supreme Pharma.
You have access to ALL emails fetched from the inbox - both complaints and non-complaints.
Use the retrieved email context below to answer user questions thoroughly and informatively.
Mention the email_id when discussing specific emails.
If an email is registered as a complaint, clearly mention its complaint_id.

=== RETRIEVED EMAILS ===
{context}
=== END CONTEXT ===

User: {user_query}
Assistant:"""

    # 4. Inject context into prompt
    full_prompt = prompt_template.format(
        context=context_str,
        user_query=query
    )

    # 5. Get LLM response
    from app.agents.complaint_summary_agent import chat_with_context
    llm_response = chat_with_context("", full_prompt)

    return {"response": llm_response,
            "contexts": contexts
            }


# ============== Pending Emails Endpoints ==============

@router.get("/emails/all")
async def get_all_emails():
    """Get ALL fetched emails (from pending_emails table)."""
    engine = create_engine("sqlite:///app\db\complaint_manager.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    pending_emails = get_all_pending_emails(session)
    session.close()

    return {
        "count": len(pending_emails),
        "emails": [
            {
                "email_id": pe.email_id,
                "sender": pe.sender,
                "recipient": pe.recipient,
                "subject": pe.subject,
                "body_snippet": pe.body_snippet,
                "email_date": pe.email_date,
                "fetched_at": pe.fetched_at,
                "is_complaint": pe.is_complaint,
                "recommendation": "Yes, register as complaint" if pe.is_complaint == 1 else "No, not a complaint",
                "classification": pe.classification,
                "is_reviewed": pe.is_reviewed,
                "complaint_id": pe.complaint_id,
            }
            for pe in pending_emails
        ]
    }


@router.get("/emails/pending")
async def get_pending_emails_endpoint():
    """Get all unreviewed pending emails (awaiting user decision)."""
    engine = create_engine("sqlite:///app\db\complaint_manager.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    pending_emails = get_pending_emails(session)
    session.close()

    return {
        "count": len(pending_emails),
        "emails": [
            {
                "email_id": pe.email_id,
                "sender": pe.sender,
                "subject": pe.subject,
                "email_date": pe.email_date,
                "is_complaint": pe.is_complaint,
                "recommendation": "Yes, register as complaint" if pe.is_complaint == 1 else "No, not a complaint",
                "classification": pe.classification,
                "complaint_id": pe.complaint_id,
            }
            for pe in pending_emails
        ]
    }


@router.post("/emails/{email_id}/create-complaint")
async def create_complaint_endpoint(email_id: str):
    """
    Create a complaint from a pending email.
    This moves the email from pending to complaints table.
    """
    engine = create_engine("sqlite:///app\db\complaint_manager.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create complaint from pending
    complaint = create_complaint_from_pending(session, email_id)

    if not complaint:
        session.close()
        raise HTTPException(status_code=404, detail=f"Pending email {email_id} not found")

    # Update ChromaDB metadata with complaint_id
    pending = get_pending_email_by_id(session, email_id)
    if pending:
        text_to_embed = f"{pending.subject}\n{pending.body_snippet or ''}"
        chroma_metadata = {
            "sender": pending.sender or "",
            "subject": pending.subject or "",
            "email_date": pending.email_date or "",
            "category": pending.classification.get("category", "") if pending.classification else "",
            "severity": pending.classification.get("severity", "") if pending.classification else "",
            "department": pending.classification.get("department", "") if pending.classification else "",
            "product": pending.classification.get("product", "") if pending.classification else "",
            "email_id": email_id,
            "complaint_id": complaint.complaint_id,
            "is_complaint": "1",
        }
        upsert_in_chromadb(email_id, text_to_embed, chroma_metadata)

    session.close()

    return {
        "status": "success",
        "message": f"Complaint {complaint.complaint_id} created from email {email_id}",
        "complaint_id": complaint.complaint_id,
        "email_id": email_id,
    }


@router.post("/emails/bulk-create-complaint")
async def bulk_create_complaints_endpoint(email_ids: list[str]):
    """
    Create complaints from multiple pending emails.
    Pass a list of email_ids in the request body.
    """
    engine = create_engine("sqlite:///app\db\complaint_manager.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    complaints = bulk_create_complaints_from_pending(session, email_ids)

    # Update ChromaDB metadata for each
    for complaint in complaints:
        pending = get_pending_email_by_id(session, complaint.email_id)
        if pending:
            text_to_embed = f"{pending.subject}\n{pending.body_snippet or ''}"
            chroma_metadata = {
                "sender": pending.sender or "",
                "subject": pending.subject or "",
                "email_date": pending.email_date or "",
                "category": pending.classification.get("category", "") if pending.classification else "",
                "severity": pending.classification.get("severity", "") if pending.classification else "",
                "department": pending.classification.get("department", "") if pending.classification else "",
                "product": pending.classification.get("product", "") if pending.classification else "",
                "email_id": complaint.email_id,
                "complaint_id": complaint.complaint_id,
                "is_complaint": "1",
            }
            upsert_in_chromadb(complaint.email_id, text_to_embed, chroma_metadata)

    session.close()

    return {
        "status": "success",
        "message": f"Created {len(complaints)} complaints",
        "complaint_ids": [c.complaint_id for c in complaints],
    }


@router.post("/complaints/create")
async def create_complaint_manual(complaint_data: dict):
    """
    Manually create a new complaint (without email source).

    Body fields (all optional except sender or subject):
    - sender: Who filed the complaint
    - recipient: Who received the complaint
    - subject: Complaint subject/title
    - body_snippet: Complaint description
    - category: Product Quality, Adverse Event, Packaging, Labeling, Delivery, Regulatory, Other
    - sub_category: Specific issue details
    - severity: Critical, High, Medium, Low
    - department: Quality Assurance, Production, Warehouse, Regulatory Affairs, Medical Affairs, Customer Service
    - product: Product name
    - batch_number: Batch/lot number
    - shift: Morning, Afternoon, Night
    """
    engine = create_engine("sqlite:///app\db\complaint_manager.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create the manual complaint
    complaint = create_manual_complaint(session, complaint_data)

    # Store in ChromaDB
    text_to_embed = f"{complaint.subject}\n{complaint.body_snippet or ''}"
    chroma_metadata = {
        "sender": complaint.sender or "",
        "subject": complaint.subject or "",
        "email_date": complaint.email_date or "",
        "category": complaint.category or "",
        "severity": complaint.severity or "",
        "department": complaint.department or "",
        "product": complaint.product or "",
        "email_id": complaint.email_id,
        "complaint_id": complaint.complaint_id,
        "is_complaint": "1",
    }
    store_in_chromadb(complaint.email_id, text_to_embed, chroma_metadata)

    session.close()

    return {
        "status": "success",
        "message": f"Complaint {complaint.complaint_id} created manually",
        "complaint_id": complaint.complaint_id,
        "email_id": complaint.email_id,
    }

