import os
import io
import json
import logging
import time
from typing import Optional, Dict, Any, List
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Structured Prompt for Business Card Extraction
SYSTEM_INSTRUCTION = """You are an expert, world-class business card parsing engine.
Analyze the business card image provided and extract the contact details with maximum precision.
Real business cards may be photographed at an angle, have creative fonts, logos, icons, multiple languages, or non-standard alignments.

CRITICAL FOCUS & DISAMBIGUATION RULE:
- If more than one business card, document, or contact info is visible in the image (for example, multiple cards on a desk/table):
  You MUST focus EXCLUSIVELY on the business card that is in the CENTER / PRIMARY TARGET FOCUS of the frame.
  Completely IGNORE any secondary cards lying nearby (above, below, or to the sides).
  Never mix details from two cards. All extracted fields must belong to the ONE centered card.

Follow these rules strictly:
1. 'full_name': The actual person's name (e.g. 'Michael Michel', 'Alex Morgan', 'Somchai Prasert'). 
   - Never confuse company names, slogans, hotel names, or greetings with the person's name.
   - If multiple names appear (e.g. bilingual card in English and another script), prioritize the primary name or combine them cleanly.
2. 'job_title': Their official role or professional position (e.g. 'General Manager', 'Chief Executive Officer', 'Senior Director of Engineering', 'Sales Executive').
3. 'company': The official business name, brand, hotel, or organization (e.g. 'Ibis Vientiane Nam Phu', 'Accor', 'Apple Inc.').
4. 'phone': Primary phone or mobile number. Keep country dialing code (+...) if visible. If multiple, format as primary number or comma-separated.
5. 'email': Direct email address (e.g. 'user@domain.com'). Must be valid email syntax.
6. 'website': Company or portfolio website URL (normalize to start with https:// if scheme is missing).
7. 'address': Full physical address, street, building, city, state, postal code, or country.
8. 'notes': Any secondary information, social handles (LinkedIn, X, WeChat), accreditations, or services mentioned.

Return ONLY a valid JSON object matching the requested schema keys:
{"full_name": "", "job_title": "", "company": "", "phone": "", "email": "", "website": "", "address": "", "notes": ""}
If any field is absent from the card, set it to an empty string ("")."""

# Models ordered by speed and availability
CASCADE_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
]

def preprocess_card_image(image_input, max_dimension: int = 1600) -> Image.Image:
    """
    Auto-orient EXIF orientation and downscale large phone camera photos.
    Supports file path, bytes, or BytesIO in-memory streams.
    """
    if isinstance(image_input, (bytes, bytearray)):
        image = Image.open(io.BytesIO(image_input))
    elif hasattr(image_input, "read"):
        image = Image.open(image_input)
    else:
        image = Image.open(image_input)

    # Fix orientation based on EXIF tag (critical for mobile camera photos)
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
        
    width, height = image.size
    if max(width, height) > max_dimension:
        scale = max_dimension / float(max(width, height))
        new_size = (int(width * scale), int(height * scale))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
        
    return image

def _get_setting(key: str, env_fallback: str, default: str = "") -> str:
    """Read configuration from system_settings DB table first, falling back to os.environ."""
    try:
        from app.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        if row and row["value"]:
            val = str(row["value"]).strip()
            if val:
                return val
    except Exception:
        pass
    return os.environ.get(env_fallback, default).strip()

def extract_card_with_gemini(image_input) -> Optional[Dict[str, Any]]:
    """
    Extract business card details using Google Gemini Multimodal Vision AI with waterfall fallback.
    Returns parsed dictionary if successful, or None if API key missing or error occurs.
    """
    api_key = _get_setting("gemini_api_key", "GEMINI_API_KEY", "")
    if not api_key:
        logger.info("GEMINI_API_KEY is not set. Falling back to local OCR.")
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        processed_image = preprocess_card_image(image_input)

        preferred_model = _get_setting("gemini_model", "GEMINI_MODEL", "gemini-3.5-flash-lite")
        models_to_try = [preferred_model] + [m for m in CASCADE_MODELS if m != preferred_model]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.1,
            response_mime_type="application/json",
        )

        for model_name in models_to_try:
            try:
                t0 = time.time()
                logger.info(f"Attempting card extraction with Gemini model: {model_name}...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        processed_image,
                        "Analyze the primary centered business card in this image. If multiple cards are visible on the desk, focus strictly on the main centered card and extract its contact fields as JSON."
                    ],
                    config=config,
                )
                elapsed = time.time() - t0

                if not response or not response.text:
                    continue

                raw_text = response.text.strip()
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                if raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]

                parsed = json.loads(raw_text.strip())

                cleaned_card = {
                    "full_name": str(parsed.get("full_name") or "").strip(),
                    "job_title": str(parsed.get("job_title") or "").strip(),
                    "company": str(parsed.get("company") or "").strip(),
                    "phone": str(parsed.get("phone") or "").strip(),
                    "email": str(parsed.get("email") or "").strip(),
                    "website": str(parsed.get("website") or "").strip(),
                    "address": str(parsed.get("address") or "").strip(),
                    "notes": str(parsed.get("notes") or "").strip(),
                    "ai_extracted": True,
                    "model_used": model_name,
                    "inference_seconds": round(elapsed, 2),
                }

                # Raw text summary
                cleaned_card["raw_text"] = (
                    f"{cleaned_card['full_name']}\n{cleaned_card['job_title']}\n"
                    f"{cleaned_card['company']}\n{cleaned_card['phone']}\n{cleaned_card['email']}"
                )

                logger.info(
                    f"Successfully extracted card in {cleaned_card['inference_seconds']}s using {model_name}: "
                    f"'{cleaned_card['full_name']}' at '{cleaned_card['company']}'"
                )
                return cleaned_card

            except Exception as model_err:
                logger.warning(f"Model {model_name} failed: {model_err}. Trying next candidate...")

        logger.error("All Gemini Vision cascade models failed. Falling back to local OCR.")
        return None

    except Exception as e:
        logger.error(f"Gemini Vision extraction setup failed: {e}. Falling back to OCR.")
        return None


def generate_followup_message(card: Dict[str, Any], context: Optional[str] = "") -> Optional[str]:
    """
    Generates a professional, personalized networking follow-up message using Gemini.
    """
    api_key = _get_setting("gemini_api_key", "GEMINI_API_KEY", "")
    if not api_key:
        return None

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        preferred_model = _get_setting("gemini_model", "GEMINI_MODEL", "gemini-3.5-flash-lite")

        clean_ctx = str(context or "").strip()
        prompt = f"""Draft a warm, professional, high-impact follow-up networking email to a contact I recently met.
Contact details:
- Name: {card.get('full_name')}
- Title: {card.get('job_title')}
- Company: {card.get('company')}
- Notes/Context: {card.get('notes') or clean_ctx or 'Met at a networking event'}

Keep the email concise (3-4 short paragraphs), natural, and engaging. Include a relevant Subject Line."""

        for model_name in [preferred_model] + [m for m in CASCADE_MODELS if m != preferred_model]:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[prompt],
                )
                if response and response.text:
                    return response.text.strip()
            except Exception:
                continue

        return None
    except Exception as e:
        logger.error(f"Follow-up generation failed: {e}")
        return None
