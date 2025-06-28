# main.py in identity-service/
import os
import uuid
import secrets
import logging
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import UUID
from urllib.parse import urlparse

import auth
import models
import database
from database import get_db

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Create all database tables on startup if they don't exist
database.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Lantern Identity Service")

# --- Middleware ---
origins_from_env_str = os.getenv("ALLOWED_ORIGINS", "https://lantern.henosis.us")
configured_origins = [o.strip() for o in origins_from_env_str.split(',')]
logging.info(f"CORS middleware configured with origins: {configured_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- FastAPI Dependency for getting the current user from a token ---
def get_current_user(db: Session = Depends(get_db), token: str = Depends(auth.oauth2_scheme)):
    payload = auth.decode_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username: str = payload.get("sub")
    user = db.query(database.User).filter(database.User.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

# --- Auth Endpoints ---
@app.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=models.UserInDB)
def register_user(user_in: models.UserCreate, db: Session = Depends(get_db)):
    """Creates a new user account."""
    existing_user = db.query(database.User).filter(database.User.username == user_in.username).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="Username already registered")
    
    hashed_password = auth.get_password_hash(user_in.password)
    db_user = database.User(username=user_in.username, password_hash=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/auth/login", response_model=models.Token)
def login_for_access_token(db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()):
    """Logs a user in and returns a JWT."""
    user = db.query(database.User).filter(database.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/validate", response_model=models.ValidateResponse)
def validate_token(request: models.ValidateRequest, db: Session = Depends(get_db)):
    """Security endpoint for media servers to validate a user token."""
    payload = auth.decode_token(request.token)
    if not payload or not payload.get("sub"):
        return models.ValidateResponse(is_valid=False)

    username = payload.get("sub")
    user = db.query(database.User).filter(database.User.username == username).first()
    server = db.query(database.Server).filter(database.Server.server_unique_id == request.server_unique_id).first()
    
    if not user or not server:
        return models.ValidateResponse(is_valid=False)

    if server.owner_id == user.id:
        return models.ValidateResponse(is_valid=True, username=user.username, is_owner=True)
    
    permission = db.query(database.SharingPermission).filter_by(user_id=user.id, server_id=server.id).first()
    if permission:
        return models.ValidateResponse(is_valid=True, username=user.username, is_owner=False)

    return models.ValidateResponse(is_valid=False)

# --- Pydantic models for server management request bodies ---
class GenerateTokenRequest(BaseModel):
    server_id: UUID

class HeartbeatRequest(BaseModel):
    server_unique_id: UUID
    url: str

class ServerAddressResponse(BaseModel):
    public_ip: str
    public_port: int
    
# --- Server Management Endpoints ---
@app.post("/servers/generate-claim-token", response_model=dict)
def generate_claim_token(request: GenerateTokenRequest, db: Session = Depends(get_db)):
    """Called by a new media server to get a short-lived claim token."""
    server_id = request.server_id
    
    db.query(database.ClaimToken).filter_by(server_unique_id=server_id).delete()

    token_str = secrets.token_urlsafe(16)[:4].upper()
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    
    claim_token = database.ClaimToken(
        token=token_str,
        server_unique_id=server_id,
        expires_at=expires
    )
    db.add(claim_token)
    db.commit()
    return {"claim_token": token_str, "expires_at": expires}

@app.post("/servers/claim", status_code=status.HTTP_201_CREATED, response_model=models.ServerInfo)
def claim_server(
    claim_request: models.ClaimRequest,
    db: Session = Depends(get_db),
    current_user: models.UserInDB = Depends(get_current_user),
):
    """Called by the frontend to link a server to a logged-in user."""
    token_record = db.query(database.ClaimToken).filter_by(token=claim_request.claim_token.upper()).first()

    if not token_record or token_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Claim token is invalid or has expired.")

    existing_server = db.query(database.Server).filter_by(server_unique_id=token_record.server_unique_id).first()
    if existing_server:
        raise HTTPException(status_code=409, detail="This server has already been claimed.")
    
    new_server = database.Server(
        server_unique_id=token_record.server_unique_id,
        owner_id=current_user.id,
        friendly_name=claim_request.friendly_name,
        local_url=claim_request.url 
    )
    db.add(new_server)
    db.delete(token_record)
    db.commit()
    db.refresh(new_server)
    
    return models.ServerInfo(
        server_unique_id=new_server.server_unique_id,
        friendly_name=new_server.friendly_name,
        last_known_url=new_server.local_url, # Keep original model for now
        is_owner=True
    )

@app.post("/servers/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def server_heartbeat(request: HeartbeatRequest, http_request: Request, db: Session = Depends(get_db)):
    """Called by a media server to update its public IP and port."""
    server = db.query(database.Server).filter_by(server_unique_id=request.server_unique_id).first()
    if not server:
        return
    
    client_host = http_request.client.host
    parsed_url = urlparse(request.url)
    
    server.local_url = request.url
    server.public_ip = client_host
    server.public_port = parsed_url.port or 80 # Default to 80 if not specified
    server.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    return

@app.get("/servers/{server_unique_id}/address", response_model=ServerAddressResponse)
def get_server_address(
    server_unique_id: UUID,
    db: Session = Depends(get_db),
    current_user: models.UserInDB = Depends(get_current_user)
):
    """Gets the last known public IP and port for a server."""
    server = db.query(database.Server).filter_by(server_unique_id=server_unique_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found.")

    # Check if user has permission
    is_owner = server.owner_id == current_user.id
    permission = db.query(database.SharingPermission).filter_by(user_id=current_user.id, server_id=server.id).first()
    
    if not is_owner and not permission:
        raise HTTPException(status_code=403, detail="You do not have permission to access this server's address.")

    if not server.public_ip or not server.public_port:
        raise HTTPException(status_code=404, detail="Server has not reported a public address yet. Make sure it's running and connected.")

    return ServerAddressResponse(public_ip=server.public_ip, public_port=server.public_port)

# --- User-Facing Endpoints ---
@app.get("/me/servers", response_model=list[models.ServerInfo])
def get_my_servers(
    db: Session = Depends(get_db),
    current_user: models.UserInDB = Depends(get_current_user),
):
    """Gets a list of all servers a user owns or has been granted access to."""
    owned_servers = db.query(database.Server).filter_by(owner_id=current_user.id).all()
    
    permissions = db.query(database.SharingPermission).filter_by(user_id=current_user.id).all()
    shared_server_ids = {p.server_id for p in permissions}
    shared_servers = db.query(database.Server).filter(database.Server.id.in_(shared_server_ids)).all()

    server_list = []
    for s in owned_servers:
        server_list.append(models.ServerInfo(
            server_unique_id=s.server_unique_id,
            friendly_name=s.friendly_name,
            last_known_url=s.local_url, # Use local_url here
            is_owner=True
        ))
    for s in shared_servers:
        server_list.append(models.ServerInfo(
            server_unique_id=s.server_unique_id,
            friendly_name=s.friendly_name,
            last_known_url=s.local_url, # And here
            is_owner=False
        ))
    return server_list

# --- Sharing Endpoints ---
@app.post("/sharing/invite", status_code=status.HTTP_201_CREATED)
def invite_user_to_server(request: models.InviteRequest, db: Session = Depends(get_db)):
    """Called by a media server (on behalf of its owner) to share access."""
    owner_server = db.query(database.Server).filter_by(server_unique_id=request.server_unique_id).first()
    invitee = db.query(database.User).filter_by(username=request.invitee_username).first()
    
    if not owner_server or not invitee:
        raise HTTPException(status_code=404, detail="Server or invitee user not found.")
    
    if owner_server.owner_id == invitee.id:
        raise HTTPException(status_code=400, detail="Cannot invite the server owner to their own server.")

    existing_perm = db.query(database.SharingPermission).filter_by(
        user_id=invitee.id, server_id=owner_server.id
    ).first()
    if existing_perm:
        raise HTTPException(status_code=409, detail="User already has permission for this server.")

    new_permission = database.SharingPermission(
        user_id=invitee.id,
        server_id=owner_server.id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
    )
    db.add(new_permission)
    db.commit()
    return {"message": f"Successfully invited {invitee.username} to server '{owner_server.friendly_name}'."}
