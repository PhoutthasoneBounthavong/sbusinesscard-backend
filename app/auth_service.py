import os
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import jwt
from fastapi import Header, HTTPException, status

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "cardr-apple-secret-key-2026-secure-jwt-token-auth")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 60

def hash_password(password: str) -> str:
    """Hash password using salt + PBKDF2 HMAC SHA-256."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000
    )
    return f"{salt}:{key.hex()}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against stored salt:hash string."""
    try:
        parts = hashed_password.split(":")
        if len(parts) != 2:
            return False
        salt, stored_hash = parts
        key = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000
        )
        return secrets.compare_digest(key.hex(), stored_hash)
    except Exception:
        return False

def create_access_token(user_id: Any, email: str, full_name: str, role: str = "user") -> str:
    """Create signed JWT access token."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    uid = int(user_id) if user_id is not None else 1
    payload = {
        "sub": str(uid),
        "user_id": uid,
        "email": email,
        "full_name": full_name,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None

def get_current_user_optional(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    """
    Extracts user info from Authorization: Bearer <token> header if provided.
    Also validates that the account is not suspended in the database.
    Does not reject unauthenticated requests (returns None).
    """
    if not authorization:
        return None
    try:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
            payload = decode_access_token(token)
            if payload and "user_id" in payload:
                # Fetch fresh role & status from database
                try:
                    import sqlite3
                    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "business_contact.db")
                    conn = sqlite3.connect(db_path, timeout=5.0)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("SELECT role, status FROM users WHERE id = ?", (payload["user_id"],))
                    row = cur.fetchone()
                    conn.close()
                    if row:
                        payload["role"] = row["role"] or payload.get("role", "user")
                        payload["status"] = row["status"] or "active"
                        if payload["status"] == "suspended":
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail="Your account has been suspended by an administrator."
                            )
                except HTTPException:
                    raise
                except Exception:
                    pass
                return payload
    except HTTPException:
        raise
    except Exception:
        pass
    return None

def get_current_user_required(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Strict dependency: rejects requests without valid Authorization Bearer token.
    """
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def require_admin(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Strict RBAC dependency: rejects requests unless the caller provides a valid JWT
    and holds 'admin' or 'super_admin' role.
    """
    user = get_current_user_required(authorization)
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Administrative privileges required."
        )
    return user
