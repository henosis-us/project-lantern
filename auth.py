# auth.py
from fastapi import HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
import requests
from database import get_db_connection  # Import to access server_config
import sqlite3

# OAuth2 scheme for token dependency, pointing to Identity Service login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8001/auth/login") #"https://lantern.henosis.us/api/auth/login"

def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Rewritten dependency to validate the user token against the remote Identity Service.
    It fetches the server_unique_id from the local database and sends it along with the token
    to the Identity Service for validation.
    """
    # Fetch server_unique_id from local database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM server_config WHERE key = 'server_unique_id'")
    row = cursor.fetchone()
    conn.close()  # Close connection early to avoid leaks

    if not row:
        raise HTTPException(status_code=500, detail="Server not configured with unique ID")

    server_unique_id = row['value']

    # Call Identity Service to validate the token
    try:
        response = requests.post(
            "http://localhost:8001/auth/validate", #"https://lantern.henosis.us/api/auth/validate"
            json={"token": token, "server_unique_id": server_unique_id},
            timeout=10  # Add a timeout to avoid hanging requests
        )
        response.raise_for_status()  # Raise an exception for HTTP errors
        result = response.json()

        if result.get("is_valid"):
            # Return the user object from the Identity Service response
            # Assuming the response includes user details like username; adjust if needed
            return result  # e.g., {"is_valid": true, "username": "user", ...}
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token or unauthorized access")
    
    except requests.RequestException as e:
        # Handle network or Identity Service errors
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Identity Service error: {str(e)}")
    except Exception as e:
        # Catch any other unexpected errors
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")