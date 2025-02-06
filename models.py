from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship with saved files
    saved_files = relationship("SavedFile", back_populates="owner")

class SavedFile(Base):
    __tablename__ = "saved_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    file_path = Column(String)
    file_type = Column(String)  # 'chat' or 'comments'
    source_id = Column(String)  # Telegram chat/channel ID
    source_name = Column(String)  # Telegram chat/channel name
    created_at = Column(DateTime, default=datetime.utcnow)
    file_metadata = Column(Text)  # JSON string for additional data (filters used, etc.)
    
    # Foreign key to user
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="saved_files") 