# models.py
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from uuid import UUID

# --- Token Models ---
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

# --- User Models ---
class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    id: int
    class Config:
        orm_mode = True

# --- Server Models ---
class ServerInfo(BaseModel):
    server_unique_id: UUID
    friendly_name: str
    last_known_url: Optional[str]
    is_owner: bool

class ClaimRequest(BaseModel):
    claim_token: str = Field(..., min_length=4, max_length=10)
    friendly_name: str
    # NEW: Add the server URL to the claim request
    url: str

# --- Validation Models ---
class ValidateRequest(BaseModel):
    token: str
    server_unique_id: UUID

class ValidateResponse(BaseModel):
    is_valid: bool
    username: Optional[str] = None
    is_owner: bool = False

# --- Sharing Models ---
class InviteRequest(BaseModel):
    server_unique_id: UUID
    invitee_username: str
    resource_type: str = "full_access"
    resource_id: str = "*"