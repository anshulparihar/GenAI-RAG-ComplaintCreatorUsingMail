from app.models.complaint_manager import Base, Complaint, PendingEmail
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import logging
from fastapi import APIRouter, HTTPException
import json
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=['Mail API'])

def get_next_complaint_id(session) -> str:
    """Generate next complaint ID in format COM_0001, COM_0002, etc."""
    last = session.query(Complaint.complaint_id).order_by(
        Complaint.id.desc()
    ).first()

    if last and last[0]:
        num = int(last[0].split("_")[1])
        next_num = num + 1
    else:
        next_num = 1

    return f"COM_{next_num:04d}"

def get_complaints(session):
    data = session.query(Complaint).all()
    session.close()
    return data


def create_manual_complaint(session, complaint_data: dict) -> Complaint:
    """
    Create a new complaint manually (without email source).
    complaint_data: dict with fields like sender, subject, body_snippet, category, etc.
    """
    complaint_id = get_next_complaint_id(session)

    complaint = Complaint(
        complaint_id=complaint_id,
        email_id=f"manual_{complaint_id}",  # Prefix to distinguish from email-sourced
        email_date=complaint_data.get("email_date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        sender=complaint_data.get("sender", ""),
        recipient=complaint_data.get("recipient", ""),
        subject=complaint_data.get("subject", ""),
        body_snippet=complaint_data.get("body_snippet", ""),
        is_complaint=1,
        category=complaint_data.get("category", ""),
        sub_category=complaint_data.get("sub_category", ""),
        severity=complaint_data.get("severity", ""),
        department=complaint_data.get("department", ""),
        product=complaint_data.get("product", ""),
        batch_number=complaint_data.get("batch_number", ""),
        shift=complaint_data.get("shift", ""),
        status="new",
    )

    session.add(complaint)
    session.commit()
    session.refresh(complaint)
    return complaint

def get_complaint_by_id(session, complaint_id: str) -> Complaint | None:
    """Fetch a single complaint by its complaint_id."""
    return session.query(Complaint).filter(
        Complaint.complaint_id == complaint_id
    ).first()

def update_complaint(session, complaint_id: str, updates: dict) -> Complaint | None:
    """
    Update fields of an existing complaint.
    updates: dict with keys matching Complaint columns.
    Returns the updated Complaint or None if not found.
    """
    complaint = get_complaint_by_id(session, complaint_id)
    if not complaint:
        return None

    for key, value in updates.items():
        if hasattr(complaint, key):
            setattr(complaint, key, value)

    complaint.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session.commit()
    session.refresh(complaint)
    return complaint

def upsert_in_complaint(session, email: dict, classification: dict):
    """
    Insert or update a complaint from email data with classification.
    email: dict with keys: id, date, from, to, subject, snippet, body
    classification: dict with keys: is_complaint, category, sub_category, severity,
                   department, product, batch_number, shift, status
    """
    existing = session.query(Complaint).filter(
        Complaint.email_id == email.get("id", "")
    ).first()

    if existing:
        logger.info(f"----Already Existing: {email.get('id')}----")
        return

    # Generate complaint_id
    complaint_id = get_next_complaint_id(session)

    complaint = Complaint(
        complaint_id=complaint_id,
        email_id=email.get("id", ""),
        email_date=email.get("date", ""),
        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        sender=email.get("from", ""),
        recipient=email.get("to", ""),
        subject=email.get("subject", ""),
        body_snippet=email.get("snippet", "") if email.get("snippet") else "",
        is_complaint=int(classification.get("is_complaint", "0")),
        category=classification.get("category", ""),
        sub_category=classification.get("sub_category", ""),
        severity=classification.get("severity", ""),
        department=classification.get("department", ""),
        product=classification.get("product", ""),
        batch_number=classification.get("batch_number", ""),
        shift=classification.get("shift", ""),
        status=classification.get("status", "new"),
    )

    session.add(complaint)
    session.commit()
    return complaint_id


# ============== PendingEmail CRUD ==============

def upsert_pending_email(session, email: dict, classification: dict):
    """
    Insert or update a pending email from email data with classification.
    ALL emails go here first - before user decides to create a complaint.
    """
    existing = session.query(PendingEmail).filter(
        PendingEmail.email_id == email.get("id", "")
    ).first()

    if existing:
        logger.info(f"----Pending Email Already Exists: {email.get('id')}----")
        return existing.email_id

    pending = PendingEmail(
        email_id=email.get("id", ""),
        sender=email.get("from", ""),
        recipient=email.get("to", ""),
        subject=email.get("subject", ""),
        body_snippet=email.get("snippet", "") if email.get("snippet") else "",
        email_date=email.get("date", ""),
        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        is_complaint=int(classification.get("is_complaint", "0")),
        classification=classification,
        is_reviewed=False,
        complaint_id=None,
    )

    session.add(pending)
    session.commit()
    return pending.email_id


def get_pending_emails(session):
    """Get all unreviewed pending emails."""
    return session.query(PendingEmail).filter(
        PendingEmail.is_reviewed == False
    ).all()


def get_all_pending_emails(session):
    """Get ALL pending emails (reviewed + unreviewed)."""
    return session.query(PendingEmail).all()


def get_pending_email_by_id(session, email_id: str) -> PendingEmail | None:
    """Fetch a pending email by email_id."""
    return session.query(PendingEmail).filter(
        PendingEmail.email_id == email_id
    ).first()


def mark_pending_email_reviewed(session, email_id: str) -> PendingEmail | None:
    """Mark a pending email as reviewed."""
    pending = get_pending_email_by_id(session, email_id)
    if pending:
        pending.is_reviewed = True
        session.commit()
        session.refresh(pending)
    return pending


def create_complaint_from_pending(session, email_id: str) -> Complaint | None:
    """
    Create a Complaint record from a PendingEmail.
    Returns the new Complaint or None if pending email not found.
    """
    pending = get_pending_email_by_id(session, email_id)
    if not pending:
        return None

    # Check if already a complaint
    existing_complaint = session.query(Complaint).filter(
        Complaint.email_id == email_id
    ).first()
    if existing_complaint:
        return existing_complaint

    complaint_id = get_next_complaint_id(session)

    complaint = Complaint(
        complaint_id=complaint_id,
        email_id=pending.email_id,
        email_date=pending.email_date,
        fetched_at=pending.fetched_at,
        sender=pending.sender,
        recipient=pending.recipient,
        subject=pending.subject,
        body_snippet=pending.body_snippet,
        is_complaint=pending.is_complaint,
        category=pending.classification.get("category", "") if pending.classification else "",
        sub_category=pending.classification.get("sub_category", "") if pending.classification else "",
        severity=pending.classification.get("severity", "") if pending.classification else "",
        department=pending.classification.get("department", "") if pending.classification else "",
        product=pending.classification.get("product", "") if pending.classification else "",
        batch_number=pending.classification.get("batch_number", "") if pending.classification else "",
        shift=pending.classification.get("shift", "") if pending.classification else "",
        status="new",
    )

    session.add(complaint)

    # Mark pending as reviewed and link complaint_id
    pending.is_reviewed = True
    pending.complaint_id = complaint_id

    session.commit()
    session.refresh(complaint)
    return complaint


def bulk_create_complaints_from_pending(session, email_ids: list[str]) -> list[Complaint]:
    """Create complaints from multiple pending emails."""
    complaints = []
    for email_id in email_ids:
        complaint = create_complaint_from_pending(session, email_id)
        if complaint:
            complaints.append(complaint)
    return complaints
