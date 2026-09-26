from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from app.config.settings import settings
from app.database.connection import connection
from app.middleware.auth import current_user

router = APIRouter(prefix="/api/auth", tags=["authentication"])
ROLES = {"retail_chemist", "clinic_phc", "charity_ngo", "patient"}

class LoginBody(BaseModel):
    email: EmailStr
    password: str

class RegisterBody(BaseModel):
    fullName: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    confirmPassword: str
    role: str
    organizationName: str | None = Field(default=None, max_length=180)
    licenseNumber: str | None = None
    registrationNumber: str | None = None
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    latitude: float | None = None
    longitude: float | None = None

def user_response(user):
    return {"id": user["id"], "fullName": user["full_name"], "email": user["email"], "phone": user["phone"], "role": user["role"], "organizationName": user["organization_name"], "nodeId": user.get("node_id")}

@router.post("/register", status_code=201)
def register(body: RegisterBody):
    if body.role not in ROLES:
        raise HTTPException(400, "Please choose a supported account type.")
    if body.password != body.confirmPassword:
        raise HTTPException(400, "Passwords do not match.")
    patient = body.role == "patient"
    if not patient and not all((body.organizationName and body.organizationName.strip(), body.address and body.address.strip(), body.city and body.city.strip(), body.state and body.state.strip())):
        raise HTTPException(400, "Organization name, address, city, and state are required for network accounts.")
    if body.role == "retail_chemist" and not body.licenseNumber:
        raise HTTPException(400, "Drug license number is required for retail chemists.")
    if body.role not in {"retail_chemist", "patient"} and not body.registrationNumber:
        raise HTTPException(400, "Registration number is required for this organization type.")
    node_type = {"retail_chemist": "pharmacy", "clinic_phc": "clinic", "charity_ngo": "charity"}.get(body.role)
    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt(rounds=12)).decode()
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id FROM users WHERE email=%s LIMIT 1", (str(body.email).lower(),))
        if cur.fetchone():
            raise HTTPException(409, "This email is already registered.")
        match = None
        if not patient:
            cur.execute("SELECT node_id FROM pharmacy_nodes WHERE LOWER(node_name)=LOWER(%s) AND LOWER(city)=LOWER(%s) AND LOWER(state)=LOWER(%s) AND LOWER(node_type)=%s LIMIT 1", (body.organizationName.strip(), body.city.strip(), body.state.strip(), node_type))
            match = cur.fetchone()
        node_id = match["node_id"] if match else None
        clean_optional = lambda value: value.strip() if value and value.strip() else None
        organization = clean_optional(body.organizationName) if not patient else None
        cur.execute("INSERT INTO users (full_name,email,phone,password_hash,role,organization_name,license_number,registration_number,address,city,state,latitude,longitude,node_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (body.fullName.strip(), str(body.email).lower(), body.phone.strip(), password_hash, body.role, organization, body.licenseNumber if body.role == "retail_chemist" else None, body.registrationNumber if body.role not in {"retail_chemist", "patient"} else None, clean_optional(body.address), clean_optional(body.city), clean_optional(body.state), body.latitude, body.longitude, node_id))
        user_id = cur.lastrowid
        conn.commit()
        cur.close()
    return {"success": True, "message": "Account created successfully. Please sign in.", "user": {"id": user_id, "fullName": body.fullName.strip(), "email": str(body.email).lower(), "phone": body.phone.strip(), "role": body.role, "organizationName": organization, "nodeId": node_id}}

@router.post("/login")
def login(body: LoginBody):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE email=%s LIMIT 1", (str(body.email).lower(),))
        user = cur.fetchone()
        cur.close()
    if not user or not user["active"] or not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "Invalid email or password.")
    token = jwt.encode({"sub": str(user["id"]), "role": user["role"], "exp": datetime.now(timezone.utc) + timedelta(hours=8)}, settings.jwt_secret, algorithm="HS256")
    return {"success": True, "token": token, "user": user_response(user)}

@router.get("/me")
def me(user=Depends(current_user)):
    return {"success": True, "user": {"id": user["id"], "fullName": user["full_name"], "email": user["email"], "phone": user["phone"], "role": user["role"], "organizationName": user["organization_name"], "nodeId": user["node_id"], "verified": bool(user["verified"]), "active": bool(user["active"])}}
