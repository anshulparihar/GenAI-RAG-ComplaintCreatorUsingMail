from app.models.complaint_manager import Base, Complaint
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import logging
from fastapi import APIRouter, HTTPException
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=['Mail API'])
def get_complaints(session):
    data = session.query(Complaint).all()
    session.close()
    return data

def upsert_in_complaint(session, emails: list):
    """
    Insert or update complaints from email data.
    emails: list of email dicts with keys: id, date, from, to, subject, snippet, body
    """
    for email in emails:
        existing = session.query(Complaint).filter(
            Complaint.email_id  == email.get("id", ""),
        )
        if existing:
            logger.info(f'----Already Existing----')
            continue
        else:
            complaint = Complaint(
                email_id=email.get("id", ""),
                email_date=email.get("date", ""),
                fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                sender=email.get("from", ""),
                recipient=email.get("to", ""),
                subject=email.get("subject", ""),
                body_snippet=email.get("snippet", "")if email.get("snippet") else "",
            )

            session.add(complaint)
            session.commit()
    session.close()
