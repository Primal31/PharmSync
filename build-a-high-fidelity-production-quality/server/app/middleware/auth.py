from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from app.config.settings import settings
from app.database.connection import connection

bearer = HTTPBearer(auto_error=False)
def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Please sign in to continue.")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise HTTPException(401, "Your session is invalid or has expired.")
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, full_name, email, phone, role, organization_name, node_id, active, verified FROM users WHERE id=%s LIMIT 1", (user_id,))
        user = cur.fetchone()
        cur.close()
    if not user or not user["active"]:
        raise HTTPException(401, "Your session is no longer active.")
    return user

def require_retail(user=Depends(current_user)):
    if user["role"] != "retail_chemist":
        raise HTTPException(403, "Only retail chemists can access pharmacy inventory.")
    return user

def require_patient(user=Depends(current_user)):
    if user["role"] != "patient":
        raise HTTPException(403, "This feature is available to patient accounts.")
    return user
