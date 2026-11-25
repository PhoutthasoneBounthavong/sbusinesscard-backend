import os
import sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ocr_service import process_card_image

def generate_sample_card_image(output_path: str):
    # Standard business card ratio: 1050 x 600 px (3.5" x 2" at 300 DPI)
    img = Image.new("RGB", (1050, 600), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # Draw simple minimalist border
    draw.rectangle([(20, 20), (1030, 580)], outline=(220, 220, 225), width=2)
    
    # Try loading a basic font, fallback to default
    try:
        font_large = ImageFont.truetype("arial.ttf", 46)
        font_medium = ImageFont.truetype("arial.ttf", 28)
        font_small = ImageFont.truetype("arial.ttf", 22)
    except IOError:
        font_large = font_medium = font_small = ImageFont.load_default()
        
    # Company Name
    draw.text((60, 60), "SBusinessCard Inc.", fill=(15, 23, 42), font=font_large)
    
    # Name & Title
    draw.text((60, 160), "Alex Morgan", fill=(15, 23, 42), font=font_large)
    draw.text((60, 220), "Chief Executive Officer & Founder", fill=(100, 116, 139), font=font_medium)
    
    # Divider line
    draw.line([(60, 280), (450, 280)], fill=(203, 213, 225), width=2)
    
    # Contact Details
    draw.text((60, 310), "Tel: +1 (555) 234-5678", fill=(51, 65, 85), font=font_small)
    draw.text((60, 350), "Email: alex.morgan@sbusinesscard.app", fill=(51, 65, 85), font=font_small)
    draw.text((60, 390), "Web: www.sbusinesscard.app", fill=(51, 65, 85), font=font_small)
    draw.text((60, 440), "1 Infinite Loop, Cupertino, CA 95014", fill=(71, 85, 105), font=font_small)
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, quality=95)
    print(f"Sample business card image generated at: {output_path}")

def test_ocr():
    test_img_path = os.path.join(os.path.dirname(__file__), "sample_card.png")
    generate_sample_card_image(test_img_path)
    
    result = process_card_image(test_img_path)
    print("OCR Processing Result:")
    print("Success:", result.get("success"))
    if result.get("success"):
        card = result["data"]
        print("Full Name:", card.get("full_name"))
        print("Job Title:", card.get("job_title"))
        print("Company:", card.get("company"))
        print("Phone:", card.get("phone"))
        print("Email:", card.get("email"))
        print("Website:", card.get("website"))
        print("Address:", card.get("address"))
        print("\n[PASS] OCR pipeline completed successfully!")
    else:
        print("OCR Error:", result.get("error"))
        sys.exit(1)

if __name__ == "__main__":
    test_ocr()
