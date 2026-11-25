import os
import shutil
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
from typing import Dict, Any, Tuple
from app.parser_service import parse_business_card

import ctypes

# Prevent decompression bomb DOS attacks
Image.MAX_IMAGE_PIXELS = 50_000_000

def get_short_path(path: str) -> str:
    """Convert long Windows path with spaces to 8.3 short path."""
    if os.name == "nt" and os.path.exists(path):
        buffer = ctypes.create_unicode_buffer(500)
        res = ctypes.windll.kernel32.GetShortPathNameW(path, buffer, 500)
        if res > 0:
            return buffer.value
    return path

# Automatically detect tesseract executable and tessdata on Windows
def configure_tesseract():
    home = os.path.expanduser("~")
    
    # Check scoop apps directory for real tesseract.exe (bypassing scoop shim)
    scoop_apps = os.path.join(home, "scoop", "apps", "tesseract")
    real_exe = None
    tessdata_path = None
    
    if os.path.exists(scoop_apps):
        for root, dirs, files in os.walk(scoop_apps):
            if "tesseract.exe" in files and "shims" not in root:
                real_exe = get_short_path(os.path.join(root, "tesseract.exe"))
                possible_td = os.path.join(root, "tessdata")
                if os.path.exists(possible_td) and os.path.exists(os.path.join(possible_td, "eng.traineddata")):
                    tessdata_path = get_short_path(possible_td)
                break

    if not tessdata_path:
        possible_tessdata = [
            os.path.join(home, "scoop", "persist", "tesseract", "tessdata"),
            r"C:\Program Files\Tesseract-OCR\tessdata",
            r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
            os.path.join(home, "AppData", "Local", "Programs", "Tesseract-OCR", "tessdata")
        ]
        for p in possible_tessdata:
            if os.path.exists(p) and os.path.exists(os.path.join(p, "eng.traineddata")):
                tessdata_path = get_short_path(p)
                break

    if tessdata_path:
        os.environ["TESSDATA_PREFIX"] = tessdata_path

    if real_exe:
        pytesseract.pytesseract.tesseract_cmd = real_exe
        return real_exe, tessdata_path

    # Fallback search
    common_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(home, "AppData", "Local", "Programs", "Tesseract-OCR", "tesseract.exe")
    ]
    for path in common_paths:
        if os.path.exists(path):
            short_cmd = get_short_path(path)
            pytesseract.pytesseract.tesseract_cmd = short_cmd
            return short_cmd, tessdata_path
            
    # Default fallback
    tesseract_cmd = shutil.which("tesseract") or "tesseract"
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    return tesseract_cmd, tessdata_path

TESSERACT_EXE, TESSDATA_DIR = configure_tesseract()




def preprocess_image_for_ocr(image_path: str) -> Image.Image:
    """
    Apply image enhancements (grayscale, contrast boost, sharpening)
    to maximize OCR character recognition rate on business cards.
    """
    img = Image.open(image_path)
    
    # Convert RGBA to RGB
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
        
    # Resize if too small (upscaling small text improves OCR precision)
    w, h = img.size
    if w < 1000 or h < 600:
        scale = max(1000 / w, 600 / h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        
    # Convert to grayscale for OCR
    gray = img.convert("L")
    
    # Enhance contrast
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(1.8)
    
    # Slight sharpening
    sharpened = enhanced.filter(ImageFilter.SHARPEN)
    
    return sharpened

def process_card_image(image_path: str) -> Dict[str, Any]:
    """
    Performs OCR and NLP parsing on a business card image.
    Returns categorized fields (name, phone, email, etc.) and raw text.
    """
    try:
        processed_img = preprocess_image_for_ocr(image_path)
        
        # When TESSDATA_PREFIX is set in os.environ, Tesseract natively reads it
        config_sparse = "--oem 3 --psm 11"
        config_block = "--oem 3 --psm 6"
        
        raw_text = pytesseract.image_to_string(processed_img, config=config_sparse)
        
        if not raw_text.strip():
            raw_text = pytesseract.image_to_string(processed_img, config=config_block)
            
        parsed_data = parse_business_card(raw_text)
        return {
            "success": True,
            "data": parsed_data,
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "data": None,
            "error": str(e)
        }


