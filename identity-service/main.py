# main.py in identity-service/
import os
import uuid
import secrets
import logging
import json  # Import json for response rewriting
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, status, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import StreamingResponse, JSONResponse # MODIFIED: Import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import UUID
from urllib.parse import urlparse
import httpx
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
origins_from_env_str = os.getenv("ALLOWED_ORIGINS", "https://lantern.henosis.us,http://localhost:5173")  # Allow localhost for local dev
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
# MODIFIED: Use the new flexible token getter auth.get_token
def get_current_user(db: Session = Depends(get_db), token: str = Depends(auth.get_token)):
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

# --- Secure Gateway Logic ---
async def _get_permitted_server_url(server_unique_id: UUID, current_user: models.UserInDB, db: Session) -> str:
    """Helper to find a server and check if the user has permission to access it."""
    server = db.query(database.Server).filter(database.Server.server_unique_id == server_unique_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    is_owner = server.owner_id == current_user.id
    permission = db.query(database.SharingPermission).filter_by(user_id=current_user.id, server_id=server.id).first()
    if not is_owner and not permission:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to access this server")
    if not server.local_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Server is currently offline or has not reported its address.")
    return server.local_url

# --- PROXY FUNCTION with trusted header and URL rewriting ---
# MODIFIED: Added server_unique_id to parameters for URL rewriting
async def _proxy_request(server_url: str, request: Request, sub_path: str, current_user: models.UserInDB, token: str, server_unique_id: UUID):
    """
    Proxies a request to the target media server.
    For stream initiation, it rewrites relative URLs in the JSON response
    to be absolute, public-facing gateway URLs.
    For all other requests, it streams the response directly.
    """
    headers_to_forward = {
        "X-Lantern-User": current_user.username,
        "X-Lantern-Is-Owner": "true" if request.state.is_owner else "false",
        "X-Lantern-Token": token,
        "Content-Type": request.headers.get("Content-Type"),
        "Accept": request.headers.get("Accept"),
    }
    headers_to_forward = {k: v for k, v in headers_to_forward.items() if v is not None}

    # MODIFIED: Increase the timeout to 60 seconds (from previous fix)
    client = httpx.AsyncClient(timeout=60.0)
    try:
        proxied_req = client.build_request(
            method=request.method,
            url=f"{server_url.rstrip('/')}/{sub_path}",
            params=request.query_params,
            content=await request.body(),
            headers=headers_to_forward
        )
        proxied_resp = await client.send(proxied_req, stream=True)

        # Check if this is a stream initiation request (JSON response from /stream endpoint)
        is_stream_init_request = sub_path.startswith("stream/") and proxied_resp.headers.get("Content-Type") == "application/json"

        if is_stream_init_request:
            # Buffer the small JSON response to rewrite it
            response_content = await proxied_resp.aread()
            await proxied_resp.aclose()
            await client.aclose()
            
            data = json.loads(response_content)

            # Construct the public base URL for the gateway
            identity_public_url = os.getenv("IDENTITY_PUBLIC_URL", "https://lantern.henosis.us")
            gateway_base = f"{identity_public_url.rstrip('/')}/gateway/{server_unique_id}"

            # Rewrite relative URLs returned by the media server to be absolute gateway URLs
            # These URLs will already contain the "?token=" query parameter from the media server
            if data.get("hls_playlist_url"):
                data["hls_playlist_url"] = f"{gateway_base}{data['hls_playlist_url']}"
            if data.get("direct_url"):
                data["direct_url"] = f"{gateway_base}{data['direct_url']}"
            if data.get("soft_sub_url"):
                data["soft_sub_url"] = f"{gateway_base}{data['soft_sub_url']}"

            # MODIFIED: Use JSONResponse to automatically handle headers and content length.
            return JSONResponse(content=data, status_code=proxied_resp.status_code)

        # For all other requests (like fetching .ts segments or other API calls), stream directly
        async def stream_generator():
            try:
                async for chunk in proxied_resp.aiter_raw():
                    yield chunk
            finally:
                await proxied_resp.aclose()
                await client.aclose()

        # Filter which headers to pass back to the client.
        response_headers = {
            "Content-Type": proxied_resp.headers.get("Content-Type"),
            "Content-Disposition": proxied_resp.headers.get("Content-Disposition"),
        }
        response_headers = {k: v for k, v in response_headers.items() if v is not None}

        return StreamingResponse(
            stream_generator(),
            status_code=proxied_resp.status_code,
            headers=response_headers
        )

    except httpx.RequestError as e:
        # Ensure the client is closed even if the initial connection fails
        await client.aclose()
        logging.error(f"Gateway request to {server_url.rstrip('/')}/{sub_path} failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Cannot connect to media server: {e}")

# Create catch-all endpoints for all common HTTP methods
@app.api_route("/gateway/{server_unique_id}/{sub_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def media_server_gateway(
    server_unique_id: UUID,
    sub_path: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.UserInDB = Depends(get_current_user), # Uses the new get_current_user
    token: str = Depends(auth.get_token), # MODIFIED: Use the new flexible token getter
):
    """Secure gateway to proxy requests to media servers."""
    server_url = await _get_permitted_server_url(server_unique_id, current_user, db)
    # Attach is_owner state to the request for use in proxy
    server = db.query(database.Server).filter(database.Server.server_unique_id == server_unique_id).first()
    request.state.is_owner = (server.owner_id == current_user.id)
    # Pass server_unique_id to the proxy function for URL rewriting
    return await _proxy_request(server_url, request, sub_path, current_user, token, server_unique_id)

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
    # Construct the correct gateway URL for the response
    identity_base_url = os.getenv("IDENTITY_PUBLIC_URL", "https://lantern.henosis.us")
    gateway_url = f"{identity_base_url}/gateway/{new_server.server_unique_id}"
    return models.ServerInfo(
        server_unique_id=new_server.server_unique_id,
        friendly_name=new_server.friendly_name,
        last_known_url=gateway_url,
        is_owner=True
    )

@app.post("/servers/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def server_heartbeat(request: HeartbeatRequest, http_request: Request, db: Session = Depends(get_db)):
    """Called by a media server to update its local URL."""
    server = db.query(database.Server).filter_by(server_unique_id=request.server_unique_id).first()
    if not server:
        return
    server.local_url = request.url
    server.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    return

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
    identity_base_url = os.getenv("IDENTITY_PUBLIC_URL", "https://lantern.henosis.us")
    def create_server_info(s, is_owner):
        gateway_url = f"{identity_base_url}/gateway/{s.server_unique_id}"
        return models.ServerInfo(
            server_unique_id=s.server_unique_id,
            friendly_name=s.friendly_name,
            last_known_url=gateway_url,
            is_owner=is_owner
        )
    for s in owned_servers:
        server_list.append(create_server_info(s, is_owner=True))
    for s in shared_servers:
        server_list.append(create_server_info(s, is_owner=False))
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
    existing_perm = db.query(database.SharingPermission).filter_by(user_id=invitee.id, server_id=owner_server.id).first()
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