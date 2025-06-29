# auth.py
import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer # NEW IMPORT HERE
from fastapi import Request, Depends, HTTPException, status # NEW: More imports for get_token

# --- Configuration ---
# It is CRITICAL to set these in your environment for production
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "a-very-secret-key-that-you-must-change")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 7)) # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# NEW: Define OAuth2PasswordBearer for token extraction
# The tokenUrl points to the Identity Service's own login endpoint.
# MODIFIED: Set auto_error=False so it doesn't raise an exception if the header is missing
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# NEW: Flexible Token Getter Dependency
async def get_token(
    request: Request,
    token_from_header: Optional[str] = Depends(oauth2_scheme)
) -> str:
    """
    Dependency to get a token from either the 'Authorization' header or a 'token' query parameter.
    This is used to authenticate both standard API calls and media stream file requests.
    """
    token = token_from_header
    if not token:
        # Check query parameters for the token
        token = request.query_params.get("token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


# --- Password Hashing ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against a hashed one."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hashes a plain password."""
    return pwd_context.hash(password)

# --- JWT Creation & Decoding ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Creates a new JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> Optional[dict]:
    """Decodes a JWT. Returns the payload or None if invalid."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None