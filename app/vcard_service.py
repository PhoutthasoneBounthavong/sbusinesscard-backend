from typing import Dict, Any, Optional
import re

def escape_vcard_val(val: Any) -> str:
    """Escape special characters and strip CRLF to prevent vCard injection."""
    if not val:
        return ""
    s = str(val).replace("\r", "").replace("\n", " ")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return s.strip()

def escape_vcard_multiline(val: Any) -> str:
    """Escape multiline text for vCard 3.0 format."""
    if not val:
        return ""
    s = str(val).replace("\r", "")
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\n", "\\n")
    return s.strip()

def generate_vcard_content(card_data: Dict[str, Any]) -> str:
    """
    Generate RFC 6350 / vCard 3.0 string compatible with
    Apple iOS Contacts, Android, Google Contacts, and Outlook.
    Sanitized against vCard property and CRLF injection.
    """
    raw_name = str(card_data.get("full_name") or "").strip() or "Business Contact"
    # Remove any control chars or newlines from full name
    clean_full_name = re.sub(r"[\r\n\t]+", " ", raw_name).strip()
    
    name_parts = clean_full_name.split()
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    company = str(card_data.get("company") or "").strip()
    job_title = str(card_data.get("job_title") or "").strip()
    phone = str(card_data.get("phone") or "").strip()
    email = str(card_data.get("email") or "").strip()
    website = str(card_data.get("website") or "").strip()
    address = str(card_data.get("address") or "").strip()
    notes = str(card_data.get("notes") or card_data.get("headline") or card_data.get("bio") or "").strip()

    vcard_lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{escape_vcard_val(clean_full_name)}",
        f"N:{escape_vcard_val(last_name)};{escape_vcard_val(first_name)};;;",
    ]
    
    if company:
        vcard_lines.append(f"ORG:{escape_vcard_val(company)}")
    if job_title:
        vcard_lines.append(f"TITLE:{escape_vcard_val(job_title)}")
    if phone:
        # Keep only valid phone characters
        clean_phone = re.sub(r"[^\d+().\s-]", "", phone).strip()
        if clean_phone:
            vcard_lines.append(f"TEL;TYPE=CELL,VOICE:{clean_phone}")
    if email:
        clean_email = re.sub(r"[\r\n\s]+", "", email)
        if clean_email:
            vcard_lines.append(f"EMAIL;TYPE=WORK,INTERNET:{clean_email}")
    if website:
        clean_url = re.sub(r"[\r\n\s]+", "", website)
        if clean_url:
            vcard_lines.append(f"URL:{clean_url}")
    if address:
        vcard_lines.append(f"ADR;TYPE=WORK:;;{escape_vcard_val(address)};;;;")
    if notes:
        vcard_lines.append(f"NOTE:{escape_vcard_multiline(notes)}")
        
    vcard_lines.append("END:VCARD")
    return "\r\n".join(vcard_lines) + "\r\n"
