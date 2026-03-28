from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class Complaint(Base):
    __tablename__ = "complaints"

    id              = Column(Integer, primary_key=True, autoincrement=True)    
    email_id        = Column(String, unique=True, nullable=False)
    email_date      = Column(String, nullable=False)
    fetched_at      = Column(String, nullable=False)

    sender          = Column(String)
    recipient       = Column(String)
    subject         = Column(String)
    body_snippet    = Column(Text)

    is_complaint    = Column(Integer, default=0)
    category        = Column(String)
    sub_category    = Column(String)
    severity        = Column(String)

    department      = Column(String)
    product         = Column(String)
    batch_number    = Column(String)
    shift           = Column(String)

    status          = Column(String, default="new")
    reviewed_by     = Column(String)
    reviewed_at     = Column(String)
    resolution      = Column(Text)

    chroma_id       = Column(String)

    created_at      = Column(String, default=lambda:
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            )
    updated_at      = Column(String, default=lambda:
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            )