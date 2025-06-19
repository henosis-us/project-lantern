# auth.py
import os, datetime, sqlite3
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends, APIRouter, Form  # Added APIRouter and Form
from fastapi.security import OAuth2PasswordBearer
from database import get_db_connection

JWT_SECRET        = os.getenv("JWT_SECRET",  "super-secret-change-me")
JWT_ALGORITHM     = "HS256"
JWT_EXPIRE_MIN    = int(os.getenv("JWT_EXPIRE_MIN", "1440"))   # 24 h default

pwd_ctx           = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme     = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ──────────────────── basic user helpers ────────────────────
def hash_pw(password: str) -> str:
    return pwd_ctx.hash(password)

def verify_pw(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def get_user(username: str) -> Optional[sqlite3.Row]:
    conn = get_db_connection()
    row  = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row

# ──────────────────── JWT helpers ───────────────────────────
def create_access_token(data: dict, expires_minutes: int = JWT_EXPIRE_MIN):
    to_encode           = data.copy()
    expire              = datetime.datetime.utcnow() + datetime.timedelta(minutes=expires_minutes)
    to_encode["exp"]    = expire
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})

# ──────────────────── FastAPI dependency ────────────────────
def get_current_user(token: str = Depends(oauth2_scheme)) -> sqlite3.Row:
    payload = decode_token(token)
    username = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=401, detail="Malformed token")
    user = get_user(username)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ──────────────────── public service functions ─────────────────────────
router = APIRouter(prefix="/auth", tags=["auth"])

def create_user(username: str, password: str, *, is_admin: bool = False):
    if get_user(username):
        raise HTTPException(status_code=409, detail="User already exists")

    pw_hash = hash_pw(password)
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
        (username, pw_hash, int(is_admin)),
    )
    conn.commit()
    conn.close()

def authenticate(username: str, password: str):
    user = get_user(username)
    if not user or not verify_pw(password, user["password_hash"]):
        return None
    return user

# ──────────────────── FastAPI end-points ───────────────────────────────
@router.post("/register")
def register(username: str = Form(...), password: str = Form(...)):
    """
    Create a user account.  On an empty DB the very first account is
    automatically flagged is_admin=1 (useful for boot-strapping).
    """
    first_user = get_db_connection().execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
    create_user(username, password, is_admin=first_user)
    return {"msg": "account created", "admin": bool(first_user)}

@router.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    user = authenticate(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user["username"]})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me")
def me(current=Depends(get_current_user)):
    return {"username": current["username"], "is_admin": bool(current["is_admin"])}