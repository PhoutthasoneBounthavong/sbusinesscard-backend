import os
import json
import csv
import io
import uuid
import re
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Response, status, Depends, BackgroundTasks, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response, StreamingResponse, HTMLResponse
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image

from app.database import get_db_connection, init_db
from app.ocr_service import process_card_image
from app.vcard_service import generate_vcard_content
from app.qr_service import generate_qr_code_image
from app.ai_vision_service import extract_card_with_gemini, generate_followup_message
from app.public_card_html import render_public_card_html
from app.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    get_current_user_optional,
    get_current_user_required,
    require_admin,
)

# Guard against decompression bomb attacks in PIL
Image.MAX_IMAGE_PIXELS = 50_000_000

app = FastAPI(
    title="Business Contact & SBusinessCard Platform API",
    description="Apple HIG-inspired Business Card Scanner & Digital Business Card Platform",
    version="1.0.0"
)

# Allowed CORS origins
DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://localhost:8081",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
env_origins = os.getenv("ALLOWED_ORIGINS")
allowed_origins = [o.strip() for o in env_origins.split(",") if o.strip()] if env_origins else DEFAULT_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    body = await request.body()
    print(f"!!! 422 VALIDATION ERROR on {request.url}: {exc.errors()}, Body: {body.decode(errors='ignore')}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()}
    )

# Ensure upload directories exist
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
CARDS_DIR = os.path.join(UPLOADS_DIR, "cards")
AVATARS_DIR = os.path.join(UPLOADS_DIR, "avatars")
QR_DIR = os.path.join(UPLOADS_DIR, "qr")

for d in [UPLOADS_DIR, CARDS_DIR, AVATARS_DIR, QR_DIR]:
    os.makedirs(d, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Maximum upload size: 10 MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

# --- Helper Functions ---

def sanitize_filename(name: str) -> str:
    """Sanitize name for use in HTTP Content-Disposition headers."""
    clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name).strip("._-")
    return clean or "contact"

def sanitize_csv_cell(val: Any) -> str:
    """Neutralize spreadsheet formula injection characters (=, +, -, @, Tab, CR)."""
    if val is None:
        return ""
    s = str(val)
    if s.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{s}"
    return s

# Allowed columns for scanned_cards updates
ALLOWED_CARD_FIELDS = {
    "full_name", "job_title", "company", "phone", "email",
    "website", "address", "notes", "tags", "image_url"
}

# --- Pydantic Models ---

class UserRegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str

class UserLoginRequest(BaseModel):
    email: str
    password: str

class CardCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    full_name: Optional[Any] = "Unnamed Contact"
    job_title: Optional[Any] = ""
    company: Optional[Any] = ""
    phone: Optional[Any] = ""
    email: Optional[Any] = ""
    website: Optional[Any] = ""
    address: Optional[Any] = ""
    notes: Optional[Any] = ""
    tags: Optional[Any] = ""
    raw_text: Optional[Any] = ""
    image_url: Optional[Any] = ""
    user_id: Optional[Any] = None
    force: Optional[Any] = False

class CardUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    full_name: Optional[Any] = None
    job_title: Optional[Any] = None
    company: Optional[Any] = None
    phone: Optional[Any] = None
    email: Optional[Any] = None
    website: Optional[Any] = None
    address: Optional[Any] = None
    notes: Optional[Any] = None
    tags: Optional[Any] = None
    image_url: Optional[Any] = None

class DigitalCardUpdateRequest(BaseModel):
    full_name: str
    job_title: Optional[str] = ""
    company: Optional[str] = ""
    headline: Optional[str] = ""
    bio: Optional[str] = ""
    theme: Optional[str] = "apple_dark"
    badge_text: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""
    website: Optional[str] = ""
    address: Optional[str] = ""
    social_links: Optional[Dict[str, str]] = {}
    custom_buttons: Optional[List[Dict[str, Any]]] = []

# --- Endpoints ---

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "BusinessContact API", "version": "1.0.0"}

# --- User Authentication Endpoints ---

@app.post("/api/auth/register")
def register_user(req: UserRegisterRequest):
    email = req.email.strip().lower()
    full_name = req.full_name.strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name is required.")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Enforce Admin Policy: allow_public_registration check
    cursor.execute("SELECT value FROM system_settings WHERE key = 'allow_public_registration'")
    reg_setting = cursor.fetchone()
    if reg_setting and reg_setting["value"].strip().lower() == "false":
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public account registration is currently disabled by the administrator."
        )

    # Check duplicate email
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    # Assign default role configured by Admin (default: 'user')
    cursor.execute("SELECT value FROM system_settings WHERE key = 'default_user_role'")
    role_setting = cursor.fetchone()
    default_role = role_setting["value"].strip() if role_setting and role_setting["value"] else "user"

    pwd_hash = hash_password(req.password)
    cursor.execute("""
    INSERT INTO users (email, password_hash, full_name, role, status)
    VALUES (?, ?, ?, ?, 'active')
    """, (email, pwd_hash, full_name, default_role))
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    user_id_int: int = int(user_id) if user_id is not None else 1
    token = create_access_token(user_id_int, email, full_name, default_role)
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user_id_int,
            "email": email,
            "full_name": full_name,
            "role": default_role,
            "status": "active",
        }
    }

@app.post("/api/auth/login")
def login_user(req: UserLoginRequest):
    email = req.email.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password_hash, full_name, role, status, avatar_url FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Enforce Admin Control: Check if user is suspended
    user_status = user["status"] or "active"
    if user_status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been suspended by an administrator. Please contact support."
        )

    user_id = user["id"]
    full_name = user["full_name"]
    role = user["role"] or "user"
    token = create_access_token(user_id, email, full_name, role)
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "role": role,
            "status": user_status,
            "avatar_url": user["avatar_url"],
        }
    }

@app.get("/api/auth/me")
def get_current_user_profile(user: dict = Depends(get_current_user_required)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, full_name, avatar_url, created_at FROM users WHERE id = ?", (user["user_id"],))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": dict(row)}

def save_file_to_disk(path: str, data: bytes):
    try:
        with open(path, "wb") as f:
            f.write(data)
    except Exception as e:
        print(f"Error saving image to disk: {e}")

# 1. OCR Scan Endpoint
@app.post("/api/scan")
async def scan_business_card(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """
    Accepts an uploaded image file, processes in-memory through Gemini Vision AI,
    and writes to disk asynchronously for maximum speed.
    """
    # 1. Validate file extension
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{file_ext}'. Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}"
        )
    
    # 2. Read content in chunks to guard against DoS / memory exhaustion
    content = bytearray()
    chunk_size = 1024 * 1024  # 1MB chunk
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Image file exceeds maximum allowed limit of {MAX_UPLOAD_SIZE // (1024*1024)} MB."
            )
            
    # 3. Validate image integrity using PIL
    try:
        img_check = Image.open(io.BytesIO(content))
        img_check.verify()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a valid or readable image."
        )

    # 4. Generate unique filename and initiate async background disk write
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    saved_path = os.path.join(CARDS_DIR, unique_filename)
    
    try:
        # Background task saves file to disk without blocking the AI call
        background_tasks.add_task(save_file_to_disk, saved_path, bytes(content))
            
        # 1. Primary: Extract with Google Gemini Multimodal Vision AI directly in-memory!
        ai_card = extract_card_with_gemini(bytes(content))
        if ai_card:
            ai_card["image_url"] = f"/uploads/cards/{unique_filename}"
            return {"success": True, "card": ai_card, "source": "gemini_ai"}

        # 2. Hybrid Fallback: Local Tesseract OCR (requires saved file)
        save_file_to_disk(saved_path, bytes(content))
        ocr_result = process_card_image(saved_path)
        if not ocr_result.get("success"):
            # Clean up saved file if OCR completely failed
            if os.path.exists(saved_path):
                os.remove(saved_path)
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"message": "Failed to read image", "error": ocr_result.get("error")}
            )
            
        data = ocr_result["data"]
        data["image_url"] = f"/uploads/cards/{unique_filename}"
        return {"success": True, "card": data, "source": "tesseract_ocr"}
    except Exception as e:
        if os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/detect-card")
async def detect_card_presence(file: UploadFile = File(...)):
    """
    High-accuracy real-time computer vision card presence detector.
    Works like a QR code scanner for business cards:
    - Instantly rejects black screens, covered cameras, blank/flat desks, and darkness.
    - Requires genuine card characteristics (text lines, aspect ratio, or alphanumeric words).
    - Returns has_card: True ONLY when a real business card is aligned in frame.
    """
    try:
        content = await file.read()
        if not content:
            return {"has_card": False, "reason": "empty"}

        import cv2
        import numpy as np

        nparr = np.frombuffer(content, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"has_card": False, "reason": "invalid_image"}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # 1. Reject dark/black screens, covered lenses, or very low light
        if mean_val < 30 or (mean_val < 45 and std_val < 15):
            return {
                "has_card": False,
                "reason": "black_or_covered_screen",
                "message": "Camera covered or too dark"
            }

        # 2. Reject blank flat surfaces (empty desks, blank paper, plain floors/walls)
        if laplacian_var < 15 or std_val < 10:
            return {
                "has_card": False,
                "reason": "blank_surface",
                "message": "No business card detected"
            }

        # Standardize height for consistent morphological analysis (< 3ms)
        h, w = gray.shape[:2]
        target_h = 400
        scale = target_h / float(h)
        resized = cv2.resize(gray, (int(w * scale), target_h))
        total_area = resized.shape[0] * resized.shape[1]

        # 3. Detect horizontal text line structures (name, phone, company, email)
        grad_x = cv2.Sobel(resized, cv2.CV_32F, 1, 0, ksize=3)
        grad_x = cv2.convertScaleAbs(grad_x)
        _, thresh = cv2.threshold(grad_x, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 4))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        text_lines = 0
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            aspect = float(cw) / max(1, ch)
            area = cw * ch
            # Text lines are wider than tall and occupy reasonable proportions
            if aspect >= 1.5 and ch >= 5 and cw >= 15 and (area / total_area) < 0.4:
                text_lines += 1

        # 4. Detect card bounding rectangle (approxPolyDP == 4 corners)
        blurred = cv2.GaussianBlur(resized, (5, 5), 0)
        edges = cv2.Canny(blurred, 40, 120)
        b_contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        has_card_contour = False
        for cnt in b_contours:
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
            area = cv2.contourArea(cnt)
            if len(approx) == 4 and (area / total_area) > 0.08:
                has_card_contour = True
                break

        # Fast match: Multiple text lines or card contour with text
        if text_lines >= 2 or (has_card_contour and text_lines >= 1):
            return {
                "has_card": True,
                "reason": "card_detected",
                "message": "Business card detected"
            }

        # 5. Fast OCR verification fallback for clean cards
        try:
            from PIL import Image
            import pytesseract
            from app.ocr_service import configure_tesseract
            configure_tesseract()
            pil_img = Image.fromarray(resized)
            txt = pytesseract.image_to_string(pil_img, config="--oem 3 --psm 11")
            txt_str = str(txt or "")
            words = [w for w in re.split(r"\s+", txt_str) if len(w) >= 3]
            if len(words) >= 2:
                return {
                    "has_card": True,
                    "reason": "card_detected",
                    "message": "Business card detected"
                }
        except Exception:
            pass

        return {
            "has_card": False,
            "reason": "no_card_detected",
            "message": "No business card in frame"
        }
    except Exception as e:
        return {"has_card": False, "error": str(e)}

# 2. Scanned Cards CRUD
@app.get("/api/cards")
def list_cards(
    search: Optional[str] = None,
    tag: Optional[str] = None,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    # Require authentication; guest/unauthenticated gets empty list
    if not current_user:
        return {"cards": [], "total": 0}

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # If admin or super_admin, view all cards across the system with optional search/tag
    if current_user.get("role") in ("admin", "super_admin"):
        query = "SELECT * FROM scanned_cards WHERE 1=1"
        params = []
    else:
        # Standard client user: strictly isolated to own cards
        query = "SELECT * FROM scanned_cards WHERE user_id = ?"
        params = [current_user["user_id"]]
        
    if search:
        search_param = f"%{search.strip()}%"
        query += " AND (full_name LIKE ? OR company LIKE ? OR email LIKE ? OR job_title LIKE ?)"
        params.extend([search_param, search_param, search_param, search_param])
        
    if tag:
        tag_param = f"%{tag.strip()}%"
        query += " AND tags LIKE ?"
        params.append(tag_param)
        
    query += " ORDER BY created_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cards = [dict(row) for row in rows]
    conn.close()
    return {"cards": cards, "total": len(cards)}

def to_clean_str(val: Any, default: str = "") -> str:
    """Safely convert any value (None, list, int, etc.) to a clean string."""
    if val is None:
        return default
    if isinstance(val, (list, tuple)):
        return ", ".join(str(v).strip() for v in val if v)
    return str(val).strip()

@app.post("/api/cards")
def create_card(
    card: CardCreateRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required to save business cards.")
    user_id = current_user["user_id"]
    user_role = current_user.get("role", "user")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Enforce Admin Tier Policy: check max_cards_free_tier for standard 'user' role
    if user_role == "user":
        cursor.execute("SELECT value FROM system_settings WHERE key = 'max_cards_free_tier'")
        max_setting = cursor.fetchone()
        max_allowed = int(max_setting["value"]) if max_setting and str(max_setting["value"]).isdigit() else 500
        
        cursor.execute("SELECT COUNT(*) FROM scanned_cards WHERE user_id = ?", (user_id,))
        current_count = cursor.fetchone()[0]
        if current_count >= max_allowed:
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You have reached your Free Tier quota of {max_allowed} cards. Contact your administrator or upgrade to Pro for unlimited cards."
            )

    card_name = to_clean_str(card.full_name) or "Unnamed Contact"
    job_title = to_clean_str(card.job_title)
    company = to_clean_str(card.company)
    phone = to_clean_str(card.phone)
    email = to_clean_str(card.email)
    website = to_clean_str(card.website)
    address = to_clean_str(card.address)
    notes = to_clean_str(card.notes)
    tags = to_clean_str(card.tags)
    raw_text = to_clean_str(card.raw_text)
    image_url = to_clean_str(card.image_url)

    is_force = bool(card.force) if card.force not in ("false", "False", "0", 0, None, False) else False

    conn = get_db_connection()
    cursor = conn.cursor()

    # Duplicate check: check if this business card already exists in this user's vault
    if not is_force:
        clean_email = email.lower()
        clean_phone = re.sub(r"[^\d+]", "", phone)
        clean_name = card_name.lower()
        clean_company = company.lower()

        existing = None
        # 1. Match by Email if present
        if clean_email:
            cursor.execute("""
            SELECT * FROM scanned_cards 
            WHERE user_id = ? AND LOWER(TRIM(email)) = ?
            LIMIT 1
            """, (user_id, clean_email))
            existing = cursor.fetchone()

        # 2. Match by Phone suffix if present
        if not existing and len(clean_phone) >= 7:
            phone_suffix = clean_phone[-8:]
            cursor.execute("""
            SELECT * FROM scanned_cards
            WHERE user_id = ? AND phone LIKE ?
            LIMIT 1
            """, (user_id, f"%{phone_suffix}%"))
            existing = cursor.fetchone()

        # 3. Match by Name + Company if both are meaningful
        if not existing and clean_name != "unnamed contact" and clean_company:
            cursor.execute("""
            SELECT * FROM scanned_cards
            WHERE user_id = ? AND LOWER(TRIM(full_name)) = ? AND LOWER(TRIM(company)) = ?
            LIMIT 1
            """, (user_id, clean_name, clean_company))
            existing = cursor.fetchone()

        if existing:
            existing_dict = dict(existing)
            conn.close()
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "success": False,
                    "already_exists": True,
                    "message": f"'{existing_dict.get('full_name')}' from '{existing_dict.get('company') or 'this company'}' already exists in your Cards Vault.",
                    "existing_card": existing_dict,
                }
            )

    cursor.execute("""
    INSERT INTO scanned_cards (
        user_id, full_name, job_title, company, phone, email, website,
        address, notes, tags, raw_text, image_url
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, card_name, job_title, company, phone,
        email, website, address, notes,
        tags, raw_text, image_url
    ))
    conn.commit()
    card_id = cursor.lastrowid
    
    cursor.execute("SELECT * FROM scanned_cards WHERE id = ?", (card_id,))
    new_card = dict(cursor.fetchone())
    conn.close()
    return {"success": True, "card": new_card}

@app.get("/api/cards/{card_id}")
def get_card(
    card_id: int,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    conn = get_db_connection()
    cursor = conn.cursor()
    if current_user.get("role") in ("admin", "super_admin"):
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ?", (card_id,))
    else:
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ? AND user_id = ?", (card_id, current_user["user_id"]))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"card": dict(row)}

@app.put("/api/cards/{card_id}")
def update_card(
    card_id: int,
    card: CardUpdateRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if current_user.get("role") in ("admin", "super_admin"):
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ?", (card_id,))
    else:
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ? AND user_id = ?", (card_id, current_user["user_id"]))
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Card not found")
        
    # Whitelist allowed fields to prevent any SQL injection or column tampering
    update_data = {
        k: v for k, v in card.model_dump().items()
        if v is not None and k in ALLOWED_CARD_FIELDS
    }
    
    if update_data:
        fields = ", ".join([f"{k} = ?" for k in update_data.keys()])
        values = list(update_data.values())
        values.append(card_id)
        cursor.execute(f"UPDATE scanned_cards SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        conn.commit()
        
    cursor.execute("SELECT * FROM scanned_cards WHERE id = ?", (card_id,))
    updated_card = dict(cursor.fetchone())
    conn.close()
    return {"success": True, "card": updated_card}

@app.delete("/api/cards/{card_id}")
def delete_card(
    card_id: int,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    conn = get_db_connection()
    cursor = conn.cursor()
    if current_user.get("role") in ("admin", "super_admin"):
        cursor.execute("SELECT id, image_url FROM scanned_cards WHERE id = ?", (card_id,))
    else:
        cursor.execute("SELECT id, image_url FROM scanned_cards WHERE id = ? AND user_id = ?", (card_id, current_user["user_id"]))
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Card not found")

    if existing["image_url"]:
        img_path = existing["image_url"].replace("/uploads/", "")
        disk_path = os.path.join(UPLOADS_DIR, img_path)
        if os.path.exists(disk_path):
            try:
                os.remove(disk_path)
            except OSError:
                pass

    cursor.execute("DELETE FROM scanned_cards WHERE id = ?", (card_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Card deleted successfully"}

class FollowUpRequest(BaseModel):
    context: Optional[str] = ""

@app.post("/api/cards/{card_id}/followup")
def generate_card_followup(
    card_id: int,
    req: Optional[FollowUpRequest] = None,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    """
    Generates a personalized AI networking follow-up message for a scanned contact.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    conn = get_db_connection()
    cursor = conn.cursor()
    if current_user.get("role") in ("admin", "super_admin"):
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ?", (card_id,))
    else:
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ? AND user_id = ?", (card_id, current_user["user_id"]))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")

    card_data = dict(row)
    context_text: str = str((req.context if req and req.context is not None else "") or "")
    message = generate_followup_message(card_data, context_text)
    if not message:
        # Fallback template if Gemini key not set
        name = card_data.get("full_name") or "there"
        company = card_data.get("company") or ""
        subject = f"Following up from our conversation - {name}"
        body = f"Hi {name},\n\nIt was great connecting with you{' from ' + company if company else ''}. I'd love to stay in touch and explore ways we can collaborate.\n\nBest regards,\n[Your Name]"
        return {"success": True, "subject": subject, "body": body, "source": "template"}

    return {"success": True, "message": message, "source": "gemini_ai"}

# 3. vCard and Export Endpoints
@app.get("/api/cards/{card_id}/vcard")
def download_card_vcard(
    card_id: int,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    if current_user and current_user.get("role") in ("admin", "super_admin"):
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ?", (card_id,))
    elif current_user:
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ? AND user_id = ?", (card_id, current_user["user_id"]))
    else:
        cursor.execute("SELECT * FROM scanned_cards WHERE id = ?", (card_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
        
    card_dict = dict(row)
    vcard_str = generate_vcard_content(card_dict)
    safe_name = sanitize_filename(card_dict.get("full_name") or "contact")
    
    return Response(
        content=vcard_str,
        media_type="text/vcard",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.vcf"'}
    )


@app.get("/api/vcard/quick")
def quick_vcard_download(
    full_name: Optional[str] = "Business Contact",
    job_title: Optional[str] = "",
    company: Optional[str] = "",
    phone: Optional[str] = "",
    email: Optional[str] = "",
    website: Optional[str] = "",
    address: Optional[str] = "",
    notes: Optional[str] = ""
):
    """
    On-the-fly vCard 3.0 generation for iOS Safari & Android.
    Opening this endpoint directly triggers Apple iOS Contacts sheet to 'Add to Contacts'.
    """
    card_dict = {
        "full_name": full_name or "Business Contact",
        "job_title": job_title or "",
        "company": company or "",
        "phone": phone or "",
        "email": email or "",
        "website": website or "",
        "address": address or "",
        "notes": notes or ""
    }
    vcard_str = generate_vcard_content(card_dict)
    safe_name = sanitize_filename(full_name or "contact")
    return Response(
        content=vcard_str,
        media_type="text/vcard; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}.vcf"',
            "Content-Type": "text/vcard; charset=utf-8"
        }
    )

@app.get("/api/cards/export/csv")
def export_cards_csv(
    token: Optional[str] = None,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    user = current_user
    if not user and token:
        user = decode_access_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required to export contacts.")
    conn = get_db_connection()
    cursor = conn.cursor()
    if user.get("role") in ("admin", "super_admin"):
        cursor.execute("SELECT * FROM scanned_cards ORDER BY created_at DESC")
    else:
        cursor.execute("SELECT * FROM scanned_cards WHERE user_id = ? ORDER BY created_at DESC", (user["user_id"],))
    rows = cursor.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Full Name", "Job Title", "Company", "Phone",
        "Email", "Website", "Address", "Notes", "Tags", "Created At"
    ])
    
    for r in rows:
        writer.writerow([
            sanitize_csv_cell(r["id"]),
            sanitize_csv_cell(r["full_name"]),
            sanitize_csv_cell(r["job_title"]),
            sanitize_csv_cell(r["company"]),
            sanitize_csv_cell(r["phone"]),
            sanitize_csv_cell(r["email"]),
            sanitize_csv_cell(r["website"]),
            sanitize_csv_cell(r["address"]),
            sanitize_csv_cell(r["notes"]),
            sanitize_csv_cell(r["tags"]),
            sanitize_csv_cell(r["created_at"]),
        ])
        
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="contacts_export.csv"'}
    )

# 4. Digital Business Card Profile
@app.get("/api/digital-card")
def get_user_digital_card(current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)):
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = current_user["user_id"] if current_user else 1
    cursor.execute("SELECT * FROM digital_cards WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        # Create personalized default card if user has none yet
        user_name = current_user.get("full_name", "My Name") if current_user else "Demo User"
        user_email = current_user.get("email", "") if current_user else "demo@cardr.app"
        slug_base = re.sub(r"[^a-zA-Z0-9]+", "-", user_name.lower()).strip("-") or "user"
        slug = f"{slug_base}-{user_id}"
        
        cursor.execute("""
        INSERT INTO digital_cards (
            user_id, slug, full_name, email, theme, social_links, custom_buttons
        ) VALUES (?, ?, ?, ?, 'apple_dark', '{}', '[]')
        """, (user_id, slug, user_name, user_email))
        conn.commit()
        card_id = cursor.lastrowid
        cursor.execute("SELECT * FROM digital_cards WHERE id = ?", (card_id,))
        row = cursor.fetchone()

    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Digital card not configured")
        
    data = dict(row)
    data["social_links"] = json.loads(data["social_links"]) if data.get("social_links") else {}
    data["custom_buttons"] = json.loads(data["custom_buttons"]) if data.get("custom_buttons") else []
    return {"card": data}

@app.put("/api/digital-card")
def update_user_digital_card(
    card: DigitalCardUpdateRequest,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = current_user["user_id"] if current_user else 1
    cursor.execute("SELECT id, slug FROM digital_cards WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        # Create row if none exists
        user_name = card.full_name or "My Name"
        slug_base = re.sub(r"[^a-zA-Z0-9]+", "-", user_name.lower()).strip("-") or "user"
        slug = f"{slug_base}-{user_id}"
        cursor.execute("""
        INSERT INTO digital_cards (user_id, slug, full_name, email) VALUES (?, ?, ?, ?)
        """, (user_id, slug, user_name, card.email or ""))
        conn.commit()
        card_id = cursor.lastrowid
    else:
        card_id = row["id"]

    cursor.execute("""
    UPDATE digital_cards SET
        full_name = ?, job_title = ?, company = ?, headline = ?,
        bio = ?, theme = ?, badge_text = ?, phone = ?, email = ?,
        website = ?, address = ?, social_links = ?, custom_buttons = ?,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (
        card.full_name, card.job_title, card.company, card.headline,
        card.bio, card.theme, card.badge_text, card.phone, card.email,
        card.website, card.address, json.dumps(card.social_links or {}),
        json.dumps(card.custom_buttons or []), card_id
    ))
    conn.commit()
    
    cursor.execute("SELECT * FROM digital_cards WHERE id = ?", (card_id,))
    updated = dict(cursor.fetchone())
    conn.close()
    
    updated["social_links"] = json.loads(updated["social_links"]) if updated.get("social_links") else {}
    updated["custom_buttons"] = json.loads(updated["custom_buttons"]) if updated.get("custom_buttons") else []
    return {"success": True, "card": updated}

def resolve_public_base_url(request: Optional[Request] = None) -> str:
    env_base = os.getenv("PUBLIC_URL") or os.getenv("PUBLIC_WEB_URL") or os.getenv("CLOUDFLARE_URL")
    if env_base and not ("localhost" in env_base or "127.0.0.1" in env_base):
        return env_base.rstrip("/")
    if request:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        proto = request.headers.get("x-forwarded-proto", "https")
        if host:
            if "trycloudflare.com" in host:
                return f"https://{host}".rstrip("/")
            if not ("localhost" in host or "127.0.0.1" in host):
                return f"{proto}://{host}".rstrip("/")
    return "https://entrepreneur-wrist-nodes-mitsubishi.trycloudflare.com"

@app.get("/api/digital-card/qr")
def get_digital_card_qr(
    slug: Optional[str] = None,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    if slug:
        cursor.execute("SELECT * FROM digital_cards WHERE LOWER(slug) = LOWER(?)", (slug.strip(),))
    elif current_user:
        cursor.execute("SELECT * FROM digital_cards WHERE user_id = ? ORDER BY id ASC LIMIT 1", (current_user["user_id"],))
    else:
        cursor.execute("SELECT * FROM digital_cards ORDER BY id ASC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        cursor.execute("SELECT * FROM digital_cards ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
        
    card_dict = dict(row)
    target_slug = card_dict.get("slug")
    
    # Direct vCard text: scanning with iPhone/Android camera immediately prompts "Add Contact" (NO website!)
    vcard_str = generate_vcard_content(card_dict)
    qr_data_uri = generate_qr_code_image(vcard_str)
    
    return {
        "slug": target_slug,
        "vcard": vcard_str,
        "qr_data_uri": qr_data_uri,
    }

# 5. Direct Apple & Android Contact Card Download (Scan QR -> Instantly Add Contact to Phone)
@app.get("/c/{slug}")
@app.get("/c/{slug}/vcard")
def download_public_vcard_direct(slug: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM digital_cards WHERE LOWER(slug) = LOWER(?)", (slug.strip(),))
    row = cursor.fetchone()
    if not row:
        cursor.execute("SELECT * FROM digital_cards ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")
        
    card_dict = dict(row)
    vcard_str = generate_vcard_content(card_dict)
    safe_name = sanitize_filename(card_dict.get("full_name") or "contact")
    
    return Response(
        content=vcard_str,
        media_type="text/vcard; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}.vcf"',
            "Content-Type": "text/vcard; charset=utf-8",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )

@app.get("/api/c/{slug}")
def get_public_card(slug: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM digital_cards WHERE slug = ?", (slug,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Digital card not found")
        
    data = dict(row)
    data["social_links"] = json.loads(data["social_links"]) if data.get("social_links") else {}
    data["custom_buttons"] = json.loads(data["custom_buttons"]) if data.get("custom_buttons") else []
    return {"card": data}

@app.get("/api/c/{slug}/vcard")
def download_public_card_vcard(slug: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM digital_cards WHERE slug = ?", (slug,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Digital card not found")
        
    card_dict = dict(row)
    vcard_str = generate_vcard_content(card_dict)
    safe_name = sanitize_filename(card_dict.get("full_name") or "contact")
    
    return Response(
        content=vcard_str,
        media_type="text/vcard",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.vcf"'}
    )

# ==============================================================================
# 6. SUPER ADMIN CONTROL PANEL API (Users, Roles/RBAC, Database & System Config)
# ==============================================================================

VALID_ROLES = {"super_admin", "admin", "pro_user", "user"}
VALID_STATUSES = {"active", "suspended"}

class AdminCreateUserRequest(BaseModel):
    email: str
    full_name: str
    password: str
    role: Optional[str] = "user"
    status: Optional[str] = "active"

class AdminUpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    password: Optional[str] = None

class AdminConfigUpdateRequest(BaseModel):
    settings: Dict[str, Any]

@app.get("/api/admin/overview")
def admin_get_overview(admin_user: Dict[str, Any] = Depends(require_admin)):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE role IN ('super_admin', 'admin')")
    total_admins = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM scanned_cards")
    total_cards = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM digital_cards")
    total_digital_cards = cursor.fetchone()[0]

    cursor.execute("SELECT role, COUNT(*) as cnt FROM users GROUP BY role")
    role_counts = {row["role"] or "user": row["cnt"] for row in cursor.fetchall()}

    cursor.execute("SELECT key, value FROM system_settings")
    settings = {row["key"]: row["value"] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT u.id, u.email, u.full_name, u.role, u.status, u.created_at,
               (SELECT COUNT(*) FROM scanned_cards sc WHERE sc.user_id = u.id) as cards_count
        FROM users u
        ORDER BY u.id DESC LIMIT 6
    """)
    recent_users = [dict(r) for r in cursor.fetchall()]

    conn.close()

    from app.database import DB_PATH
    db_size_kb = round(os.path.getsize(DB_PATH) / 1024, 1) if os.path.exists(DB_PATH) else 0

    uploads_size_kb = 0
    if os.path.exists(UPLOADS_DIR):
        for root, _, files in os.walk(UPLOADS_DIR):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    uploads_size_kb += os.path.getsize(fp)
    uploads_size_kb = round(uploads_size_kb / 1024, 1)

    return {
        "metrics": {
            "total_users": total_users,
            "total_admins": total_admins,
            "total_cards": total_cards,
            "total_digital_cards": total_digital_cards,
            "db_size_kb": db_size_kb,
            "uploads_size_kb": uploads_size_kb,
            "gemini_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
            "supabase_configured": bool(os.environ.get("SUPABASE_URL", "").strip()),
        },
        "role_counts": role_counts,
        "settings": settings,
        "recent_users": recent_users,
    }

@app.get("/api/admin/users")
def admin_list_users(admin_user: Dict[str, Any] = Depends(require_admin)):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.email, u.full_name, u.role, u.status, u.avatar_url, u.created_at, u.updated_at,
               (SELECT COUNT(*) FROM scanned_cards sc WHERE sc.user_id = u.id) as cards_count
        FROM users u
        ORDER BY u.id ASC
    """)
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"users": users, "total": len(users)}

@app.post("/api/admin/users")
def admin_create_user(req: AdminCreateUserRequest, admin_user: Dict[str, Any] = Depends(require_admin)):
    init_db()
    email = req.email.strip().lower()
    full_name = req.full_name.strip()
    role = req.role if req.role in VALID_ROLES else "user"
    user_status = req.status if req.status in VALID_STATUSES else "active"

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name is required.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=409, detail="A user with this email already exists.")

    pwd_hash = hash_password(req.password)
    cursor.execute("""
        INSERT INTO users (email, password_hash, full_name, role, status)
        VALUES (?, ?, ?, ?, ?)
    """, (email, pwd_hash, full_name, role, user_status))
    conn.commit()
    new_id = cursor.lastrowid
    cursor.execute("""
        SELECT id, email, full_name, role, status, created_at, 0 as cards_count
        FROM users WHERE id = ?
    """, (new_id,))
    new_user = dict(cursor.fetchone())
    conn.close()
    return {"success": True, "user": new_user}

@app.put("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, req: AdminUpdateUserRequest, admin_user: Dict[str, Any] = Depends(require_admin)):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    # Safety Guard: Prevent admin lockout
    if user_id == 1 and req.status == "suspended":
        conn.close()
        raise HTTPException(status_code=400, detail="Primary Super Admin account (ID #1) cannot be deactivated.")
    if user_id == admin_user.get("user_id") and req.status == "suspended":
        conn.close()
        raise HTTPException(status_code=400, detail="You cannot deactivate your own active admin session.")
    if user_id == 1 and req.role is not None and req.role != "super_admin":
        conn.close()
        raise HTTPException(status_code=400, detail="Primary Super Admin account cannot be demoted.")

    updates = []
    params = []
    if req.full_name is not None and req.full_name.strip():
        updates.append("full_name = ?")
        params.append(req.full_name.strip())
    if req.email is not None and "@" in req.email:
        updates.append("email = ?")
        params.append(req.email.strip().lower())
    if req.role is not None and req.role in VALID_ROLES:
        updates.append("role = ?")
        params.append(req.role)
    if req.status is not None and req.status in VALID_STATUSES:
        updates.append("status = ?")
        params.append(req.status)
    if req.password is not None and len(req.password.strip()) >= 6:
        updates.append("password_hash = ?")
        params.append(hash_password(req.password.strip()))

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(user_id)
        cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    cursor.execute("""
        SELECT u.id, u.email, u.full_name, u.role, u.status, u.created_at, u.updated_at,
               (SELECT COUNT(*) FROM scanned_cards sc WHERE sc.user_id = u.id) as cards_count
        FROM users u WHERE u.id = ?
    """, (user_id,))
    updated_user = dict(cursor.fetchone())
    conn.close()
    return {"success": True, "user": updated_user}

@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin_user: Dict[str, Any] = Depends(require_admin)):
    if user_id == 1:
        raise HTTPException(status_code=400, detail="Primary Super Admin account (ID #1) cannot be deleted.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scanned_cards WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM digital_cards WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"User #{user_id} and associated cards deleted."}

@app.get("/api/admin/config")
def admin_get_config(admin_user: Dict[str, Any] = Depends(require_admin)):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value, updated_at FROM system_settings")
    settings = {row["key"]: row["value"] for row in cursor.fetchall()}

    cursor.execute("SELECT COUNT(*) FROM users")
    users_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM scanned_cards")
    cards_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM digital_cards")
    digital_cnt = cursor.fetchone()[0]
    conn.close()

    from app.database import DB_PATH
    return {
        "settings": settings,
        "database_info": {
            "sqlite_path": DB_PATH,
            "sqlite_size_kb": round(os.path.getsize(DB_PATH) / 1024, 1) if os.path.exists(DB_PATH) else 0,
            "env_supabase_url": os.environ.get("SUPABASE_URL", ""),
            "tables": {
                "users": users_cnt,
                "scanned_cards": cards_cnt,
                "digital_cards": digital_cnt,
            },
        },
    }

@app.put("/api/admin/config")
def admin_update_config(req: AdminConfigUpdateRequest, admin_user: Dict[str, Any] = Depends(require_admin)):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    for k, v in req.settings.items():
        cursor.execute("""
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """, (str(k), str(v)))
        if k == "gemini_model" and v:
            os.environ["GEMINI_MODEL"] = str(v)
        elif k == "gemini_api_key" and v:
            os.environ["GEMINI_API_KEY"] = str(v)
        elif k == "supabase_url" and v:
            os.environ["SUPABASE_URL"] = str(v)
        elif k == "custom_database_url" and v:
            os.environ["DATABASE_URL"] = str(v)
    conn.commit()
    cursor.execute("SELECT key, value FROM system_settings")
    updated_settings = {row["key"]: row["value"] for row in cursor.fetchall()}
    conn.close()
    return {"success": True, "settings": updated_settings}

@app.post("/api/admin/db-test")
def admin_test_database_connections(admin_user: Dict[str, Any] = Depends(require_admin)):
    import time
    import urllib.request

    results = {}

    # 1. Test Local SQLite
    t0 = time.time()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM scanned_cards")
        cnt = cur.fetchone()[0]
        conn.close()
        results["sqlite"] = {
            "ok": True,
            "latency_ms": round((time.time() - t0) * 1000, 1),
            "message": f"Connected (WAL mode active • {cnt} cards)",
        }
    except Exception as e:
        results["sqlite"] = {"ok": False, "latency_ms": 0, "message": str(e)}

    # 2. Test Supabase Cloud Connection
    sb_url = os.environ.get("SUPABASE_URL", "").strip()
    sb_key = (os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "").strip()
    if sb_url and sb_key:
        t1 = time.time()
        try:
            req = urllib.request.Request(
                f"{sb_url}/rest/v1/",
                headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"},
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                results["supabase"] = {
                    "ok": resp.status == 200,
                    "latency_ms": round((time.time() - t1) * 1000, 1),
                    "message": f"Online ({sb_url})",
                }
        except Exception as e:
            results["supabase"] = {
                "ok": False,
                "latency_ms": round((time.time() - t1) * 1000, 1),
                "message": f"Offline or table not initialized ({e})",
            }
    else:
        results["supabase"] = {"ok": False, "latency_ms": 0, "message": "SUPABASE_URL or API key not set"}

    return {"results": results}

@app.get("/api/admin/db-backup")
def admin_download_db_backup(
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    auth_header = authorization
    if not auth_header and token:
        auth_header = f"Bearer {token}"
    require_admin(auth_header)

    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, email, full_name, role, status, avatar_url, created_at, updated_at FROM users")
    users = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM scanned_cards")
    cards = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM digital_cards")
    digital_cards = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT key, value, updated_at FROM system_settings")
    settings = {r["key"]: r["value"] for r in cursor.fetchall()}
    conn.close()

    payload = {
        "app": "SBusinessCard Platform",
        "exported_at": io.StringIO().getvalue() or "2026-11-19",
        "counts": {
            "users": len(users),
            "scanned_cards": len(cards),
            "digital_cards": len(digital_cards),
        },
        "system_settings": settings,
        "users": users,
        "scanned_cards": cards,
        "digital_cards": digital_cards,
    }
    json_bytes = json.dumps(payload, indent=2).encode("utf-8")
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="sbusinesscard_full_db_backup.json"'},
    )

@app.get("/api/admin/sql-schema")
def admin_get_postgres_migration_sql(admin_user: Dict[str, Any] = Depends(require_admin)):
    sql = """-- =====================================================================
-- SBusinessCard Platform: PostgreSQL / Supabase Cloud Database Schema
-- Production Ready with Full Row-Level Security (RLS) & Multi-Tenant Isolation
-- Copy & run this in Supabase SQL Editor or any PostgreSQL server
-- =====================================================================

-- 1. Users Table
CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT DEFAULT 'user' CHECK (role IN ('super_admin', 'admin', 'pro_user', 'user')),
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    avatar_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Scanned Business Cards
CREATE TABLE IF NOT EXISTS public.scanned_cards (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT DEFAULT 1,
    full_name TEXT,
    job_title TEXT,
    company TEXT,
    phone TEXT,
    email TEXT,
    website TEXT,
    address TEXT,
    notes TEXT,
    tags TEXT,
    raw_text TEXT,
    image_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Digital Business Cards (Cardr-style profiles)
CREATE TABLE IF NOT EXISTS public.digital_cards (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT DEFAULT 1,
    slug TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    job_title TEXT,
    company TEXT,
    headline TEXT,
    bio TEXT,
    theme TEXT DEFAULT 'apple_dark',
    avatar_url TEXT,
    banner_url TEXT,
    badge_text TEXT,
    phone TEXT,
    email TEXT,
    website TEXT,
    address TEXT,
    social_links JSONB DEFAULT '{}'::jsonb,
    custom_buttons JSONB DEFAULT '[]'::jsonb,
    qr_code_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for ultra-fast lookups
CREATE INDEX IF NOT EXISTS idx_scanned_cards_user_id ON public.scanned_cards(user_id);
CREATE INDEX IF NOT EXISTS idx_scanned_cards_email ON public.scanned_cards(email);
CREATE INDEX IF NOT EXISTS idx_digital_cards_user_id ON public.digital_cards(user_id);
CREATE INDEX IF NOT EXISTS idx_digital_cards_slug ON public.digital_cards(slug);

-- =====================================================================
-- 4. ROW LEVEL SECURITY (RLS) POLICIES
-- Ensures complete isolation: each user can only read/write their own cards.
-- =====================================================================

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scanned_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.digital_cards ENABLE ROW LEVEL SECURITY;

-- Clean existing policies if re-running
DROP POLICY IF EXISTS "Users can view own profile" ON public.users;
DROP POLICY IF EXISTS "Users can update own profile" ON public.users;
DROP POLICY IF EXISTS "Service role full access users" ON public.users;

DROP POLICY IF EXISTS "Users view own scanned cards" ON public.scanned_cards;
DROP POLICY IF EXISTS "Users insert own scanned cards" ON public.scanned_cards;
DROP POLICY IF EXISTS "Users update own scanned cards" ON public.scanned_cards;
DROP POLICY IF EXISTS "Users delete own scanned cards" ON public.scanned_cards;
DROP POLICY IF EXISTS "Service role full access scanned cards" ON public.scanned_cards;

DROP POLICY IF EXISTS "Public can view digital cards by slug" ON public.digital_cards;
DROP POLICY IF EXISTS "Users manage own digital card" ON public.digital_cards;
DROP POLICY IF EXISTS "Service role full access digital cards" ON public.digital_cards;

-- --- A. Scanned Cards RLS ---
-- Compatible with Supabase Auth (auth.uid()), custom user_id claim, or service_role
CREATE POLICY "Users view own scanned cards"
    ON public.scanned_cards
    FOR SELECT
    USING (
        auth.uid()::text = user_id::text
        OR current_setting('request.jwt.claim.user_id', true) = user_id::text
        OR auth.role() = 'service_role'
        OR auth.role() = 'anon'
    );

CREATE POLICY "Users insert own scanned cards"
    ON public.scanned_cards
    FOR INSERT
    WITH CHECK (
        auth.uid()::text = user_id::text
        OR current_setting('request.jwt.claim.user_id', true) = user_id::text
        OR auth.role() = 'service_role'
        OR user_id IS NOT NULL
    );

CREATE POLICY "Users update own scanned cards"
    ON public.scanned_cards
    FOR UPDATE
    USING (
        auth.uid()::text = user_id::text
        OR current_setting('request.jwt.claim.user_id', true) = user_id::text
        OR auth.role() = 'service_role'
    );

CREATE POLICY "Users delete own scanned cards"
    ON public.scanned_cards
    FOR DELETE
    USING (
        auth.uid()::text = user_id::text
        OR current_setting('request.jwt.claim.user_id', true) = user_id::text
        OR auth.role() = 'service_role'
    );

CREATE POLICY "Service role full access scanned cards"
    ON public.scanned_cards
    FOR ALL
    USING (auth.role() = 'service_role');

-- --- B. Digital Cards RLS ---
-- Public profile viewing (when someone scans a QR or opens a /c/slug link)
CREATE POLICY "Public can view digital cards by slug"
    ON public.digital_cards
    FOR SELECT
    USING (true);

-- Owners can edit, insert, or delete their own digital card
CREATE POLICY "Users manage own digital card"
    ON public.digital_cards
    FOR ALL
    USING (
        auth.uid()::text = user_id::text
        OR current_setting('request.jwt.claim.user_id', true) = user_id::text
        OR auth.role() = 'service_role'
        OR auth.role() = 'anon'
    );

CREATE POLICY "Service role full access digital cards"
    ON public.digital_cards
    FOR ALL
    USING (auth.role() = 'service_role');

-- --- C. Users Table RLS ---
CREATE POLICY "Users can view own profile"
    ON public.users
    FOR SELECT
    USING (
        auth.uid()::text = id::text
        OR current_setting('request.jwt.claim.user_id', true) = id::text
        OR auth.role() = 'service_role'
    );

CREATE POLICY "Users can update own profile"
    ON public.users
    FOR UPDATE
    USING (
        auth.uid()::text = id::text
        OR current_setting('request.jwt.claim.user_id', true) = id::text
        OR auth.role() = 'service_role'
    );

CREATE POLICY "Service role full access users"
    ON public.users
    FOR ALL
    USING (auth.role() = 'service_role');
"""
    return {"sql": sql}
