from fastapi import HTTPException, Depends, status, Query, Header, Request
import requests
from database import get_db_connection
import sqlite3
import os

IDENTITY_SERVICE_URL = os.getenv("IDENTITY_SERVICE_URL", "http://localhost:8001")

def _validate_token_with_identity_service(token: str):
    """
    Internal function to handle the actual validation logic.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM server_config WHERE key = 'server_unique_id'")
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=500, detail="Server not configured with unique ID")
    server_unique_id = row['value']
    try:
        response = requests.post(
            f"{IDENTITY_SERVICE_URL}/auth/validate",
            json={"token": token, "server_unique_id": server_unique_id},
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        if result.get("is_valid"):
            result['token'] = token
            return result
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token or unauthorized access")
    except requests.RequestException as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Identity Service error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")

def get_user_from_query(token: str = Query(..., title="Direct Play Auth Token")):
    """
    Dependency to validate a user token passed as a query parameter.
    Used for authenticating media streams where headers are not easily set.
    """
    return _validate_token_with_identity_service(token)

def get_user_from_gateway(
    request: Request,
    x_lantern_user: str = Header(None, alias="X-Lantern-User"),
    x_lantern_is_owner: bool = Header(False, alias="X-Lantern-Is-Owner")
):
    """
    Trusts the user info passed from the identity gateway.
    This is secure because the media server is not directly exposed to the internet.
    """
    if not x_lantern_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing trusted user header. Access must be via the gateway."
        )
    # Return a user-like dictionary that the endpoints can use
    return {"username": x_lantern_user, "is_owner": x_lantern_is_owner}