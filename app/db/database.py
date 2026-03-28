from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.complaint_manager import Base

# This creates a file named 'complaint_manager.db' in your folder
engine = create_engine("sqlite:///app\db\complaint_manager.db")

# Create tables from SQLAlchemy models
Base.metadata.create_all(engine)

# Create session factory
Session = sessionmaker(bind=engine)
session = Session()
