import sys
import os

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.parser_service import parse_business_card

def test_card_parsing():
    sample_ocr_text = """
    SBUSINESSCARD INC.
    Alex Morgan
    Chief Executive Officer & Founder
    
    Direct: +1 (555) 234-5678
    Mobile: +1 (555) 987-6543
    Email: alex.morgan@sbusinesscard.app
    Website: www.sbusinesscard.app
    
    1 Infinite Loop, Suite 400
    Cupertino, CA 95014
    United States
    """
    
    result = parse_business_card(sample_ocr_text)
    print("Parsed result:")
    for k, v in result.items():
        if k != "raw_text":
            print(f"  {k}: {v}")
            
    assert result["full_name"] == "Alex Morgan", f"Expected 'Alex Morgan', got '{result['full_name']}'"
    assert "Chief Executive Officer" in result["job_title"], f"Got '{result['job_title']}'"
    assert "SBUSINESSCARD" in result["company"].upper(), f"Got '{result['company']}'"
    assert result["email"] == "alex.morgan@sbusinesscard.app", f"Got '{result['email']}'"
    assert "555" in result["phone"], f"Got '{result['phone']}'"
    assert "sbusinesscard.app" in result["website"], f"Got '{result['website']}'"
    assert "Cupertino" in result["address"], f"Got '{result['address']}'"

    print("\n[PASS] All business card entity parser tests PASSED successfully!")

if __name__ == "__main__":
    test_card_parsing()
