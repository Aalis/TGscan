from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: str

class UserCreate(UserBase):
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class SavedFileBase(BaseModel):
    filename: str
    file_type: str
    source_id: str
    source_name: str
    file_metadata: Optional[str] = None

class SavedFileCreate(SavedFileBase):
    pass

class SavedFile(SavedFileBase):
    id: int
    file_path: str
    created_at: datetime
    owner_id: int

    class Config:
        from_attributes = True

class UserWithFiles(User):
    saved_files: List[SavedFile] = []

    class Config:
        from_attributes = True 