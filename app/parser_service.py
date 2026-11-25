import re
from typing import Dict, Any, List, Optional

# Common titles and corporate role taxonomy
COMMON_JOB_TITLES = [
    # C-Level & Executives
    "chief executive officer", "ceo", "chief technology officer", "cto",
    "chief financial officer", "cfo", "chief operating officer", "coo",
    "chief marketing officer", "cmo", "chief product officer", "cpo",
    "chief information officer", "cio", "president", "vice president", "vp",
    "founder", "co-founder", "managing director", "executive director", "general manager",
    "partner", "managing partner", "principal", "board member", "chairman", "chairwoman",
    
    # Tech, Engineering & Design
    "software engineer", "senior software engineer", "full stack developer", "frontend developer",
    "backend developer", "mobile developer", "ios developer", "android developer",
    "software architect", "solutions architect", "cloud architect", "systems engineer",
    "product designer", "ui/ux designer", "lead designer", "creative director", "art director",
    "product manager", "senior product manager", "head of product", "head of engineering",
    "data scientist", "machine learning engineer", "ai researcher", "devops engineer",
    "qa engineer", "tech lead", "technical lead", "engineering manager",
    
    # Business, Sales, Marketing & Operations
    "business development", "account executive", "sales manager", "sales director",
    "marketing director", "marketing manager", "growth marketer", "digital strategist",
    "brand strategist", "operations manager", "head of operations", "project manager",
    "scrum master", "consultant", "senior consultant", "advisor", "specialist",
    "financial analyst", "attorney", "legal counsel", "general counsel", "associate"
]

COMPANY_SUFFIXES = [
    r"\binc\.?\b", r"\bllc\.?\b", r"\bltd\.?\b", r"\bcorp\.?\b", r"\bcorporation\b",
    r"\bco\.?\b", r"\bcompany\b", r"\bgroup\b", r"\blabs\b", r"\bstudio\b", r"\bstudios\b",
    r"\btechnologies\b", r"\btech\b", r"\bsolutions\b", r"\bholdings\b", r"\bcapital\b",
    r"\benterprises\b", r"\bgmbh\b", r"\bag\b", r"\bs\.a\.\b", r"\bplc\b", r"\bpty\b",
    r"\bagency\b", r"\bpartners\b", r"\bassociates\b"
]

ADDRESS_INDICATORS = [
    r"\bstreet\b", r"\bst\.?\b", r"\bavenue\b", r"\bave\.?\b", r"\bboulevard\b", r"\bblvd\.?\b",
    r"\broad\b", r"\brd\.?\b", r"\bdrive\b", r"\bdr\.?\b", r"\blane\b", r"\bln\.?\b",
    r"\bway\b", r"\bsuite\b", r"\bste\.?\b", r"\bfloor\b", r"\bfl\.?\b", r"\bbuilding\b",
    r"\bbldg\.?\b", r"\bhighway\b", r"\bhwy\.?\b", r"\bpkway\b", r"\bparkway\b",
    r"\bzip\b", r"\bpostal\b", r"\bca\b", r"\bny\b", r"\btx\b", r"\bfl\b", r"\bil\b",
    r"\busa\b", r"\bunited states\b", r"\bcanada\b", r"\buk\b", r"\bgermany\b", r"\bfrance\b"
]

def clean_text_lines(raw_text: str) -> List[str]:
    """Clean raw OCR text into trimmed non-empty lines."""
    lines = []
    for line in raw_text.split("\n"):
        line = line.strip()
        # Remove weird OCR artifacts or single punctuation characters
        if len(line) > 1 and not re.match(r"^[^a-zA-Z0-9]+$", line):
            lines.append(line)
    return lines

def extract_emails(text: str) -> List[str]:
    """Extract email addresses from text."""
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    matches = re.findall(pattern, text)
    # Deduplicate while preserving order
    seen = set()
    emails = []
    for m in matches:
        m_clean = m.lower().strip(".,;:()[]\"'")
        if m_clean not in seen:
            seen.add(m_clean)
            emails.append(m_clean)
    return emails

def extract_phones(text: str) -> List[str]:
    """Extract phone and mobile numbers."""
    pattern = r"(?:\+?\d{1,4}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}(?:[-.\s]?\d{1,5})?"
    
    prefix_pattern = r"(?:tel|phone|ph|mobile|mob|cell|direct|dir|fax|call|t|m)\s*[:.-]?\s*([+\d().\s-]{7,25})"
    prefixed_matches = re.findall(prefix_pattern, text, re.IGNORECASE)
    
    all_candidates = []
    if prefixed_matches:
        all_candidates.extend(prefixed_matches)
        
    for match in re.findall(pattern, text):
        cleaned = re.sub(r"[^\d+]", "", match)
        digit_count = len(re.sub(r"\D", "", cleaned))
        if 7 <= digit_count <= 15:
            all_candidates.append(match.strip())

    cleaned_phones = []
    seen = set()
    for cand in all_candidates:
        cand_clean = cand.replace("\n", " ").replace("\r", "").strip(" .,;:()[]\"'-")
        cand_digits = re.sub(r"\D", "", cand_clean)
        if cand_digits and cand_digits not in seen:
            seen.add(cand_digits)
            cleaned_phones.append(cand_clean)
            
    return cleaned_phones

def extract_websites(text: str, emails: List[str]) -> List[str]:
    """Extract website URLs, excluding emails and invalid domains."""
    # Remove all emails from the text to prevent matching email prefixes (e.g. john.doe)
    text_without_emails = text
    for email in emails:
        text_without_emails = text_without_emails.replace(email, " ")
        
    pattern = r"(?:https?:\/\/)?(?:www\.)?([a-zA-Z0-9][-a-zA-Z0-9]*\.(?:com|org|net|io|co|ai|app|dev|me|biz|info|tech|agency|design|cloud|us|uk|de|fr|ca|au|in|jp|cn|th|sg)[a-zA-Z0-9\/._~%+-]*)"
    matches = re.findall(pattern, text_without_emails, re.IGNORECASE)
    
    websites = []
    seen = set()
    for domain in matches:
        domain_clean = domain.lower().strip(".,;:()[]\"' ")
        if domain_clean in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"]:
            continue
        if domain_clean not in seen:
            seen.add(domain_clean)
            if not domain_clean.startswith("http://") and not domain_clean.startswith("https://"):
                websites.append(f"https://{domain_clean}")
            else:
                websites.append(domain_clean)
                
    return websites


def extract_job_title(lines: List[str]) -> Optional[str]:
    """Identify job title from lines matching known roles."""
    for line in lines:
        lower_line = line.lower()
        for title in COMMON_JOB_TITLES:
            # Word boundary matching or contains
            if re.search(r"\b" + re.escape(title) + r"\b", lower_line):
                return line.strip()
    return None

def extract_company(lines: List[str], emails: List[str], websites: List[str], job_title: Optional[str]) -> Optional[str]:
    """Identify company name using suffixes, email domains, or header lines."""
    # 1. Look for explicit company legal suffixes
    for line in lines:
        if line == job_title:
            continue
        lower_line = line.lower()
        for suffix in COMPANY_SUFFIXES:
            if re.search(suffix, lower_line, re.IGNORECASE):
                # Clean off trailing phone or address
                return line.split("|")[0].split("•")[0].strip()
                
    # 2. Look at domain from corporate website or email
    for site in websites:
        m = re.search(r"(?:https?:\/\/)?(?:www\.)?([a-zA-Z0-9-]+)\.", site)
        if m:
            domain_name = m.group(1).capitalize()
            if domain_name.lower() not in ["cardr", "linkedin", "github", "twitter"]:
                # Check if this name appears in any line
                for line in lines:
                    if domain_name.lower() in line.lower() and line != job_title:
                        return line.strip()
                return f"{domain_name} Inc."
                
    # 3. Fallback: Check top lines for non-name header
    for line in lines[:3]:
        if line != job_title and len(line) > 3 and not re.search(r"[@\d]", line):
            # Check if it has 1-4 capitalized words
            words = line.split()
            if 1 <= len(words) <= 4:
                return line.strip()
                
    return None

def extract_address(lines: List[str]) -> Optional[str]:
    """Identify address lines from typical street/suite/city patterns."""
    address_lines = []
    for line in lines:
        lower_line = line.lower()
        has_indicator = any(re.search(ind, lower_line) for ind in ADDRESS_INDICATORS)
        has_digits = bool(re.search(r"\d+", line))
        
        # If it has street words or zip codes
        if has_indicator or (has_digits and re.search(r"\b\d{5}(?:-\d{4})?\b", line)):
            # Ignore lines that are clearly phone numbers or email
            if not re.search(r"[@]|(?:tel|phone|ph|mobile|cell|fax):", lower_line):
                address_lines.append(line.strip())
                
    if address_lines:
        return ", ".join(address_lines)
    return None

def extract_name(lines: List[str], job_title: Optional[str], company: Optional[str], emails: List[str]) -> Optional[str]:
    """Identify person's full name based on positioning and linguistics."""
    # Try using email prefix hint (e.g., alex.morgan -> Alex Morgan)
    email_name_hints = []
    for email in emails:
        prefix = email.split("@")[0]
        parts = re.split(r"[._-]", prefix)
        if len(parts) >= 2:
            email_name_hints = [p.lower() for p in parts if len(p) > 1]
            
    # Check top 5 lines
    for line in lines[:5]:
        if line == job_title or line == company:
            continue
            
        # Ignore lines with phone numbers, emails, URLs, or digits
        if re.search(r"[@\d\/\\:]", line):
            continue
            
        words = line.split()
        # Full names are typically 2 to 4 words
        if 2 <= len(words) <= 4:
            # Check if all words start with uppercase or match email hints
            is_title_case = all(w[0].isupper() for w in words if w)
            matches_email_hint = any(h in line.lower() for h in email_name_hints)
            
            if is_title_case or matches_email_hint:
                return line.strip()
                
    # Fallback to the first alphabetic line
    for line in lines[:3]:
        if line != job_title and line != company and len(line.split()) in [2, 3]:
            return line.strip()
            
    return None

def parse_business_card(raw_text: str) -> Dict[str, Any]:
    """
    Main pipeline: Analyzes raw OCR text, categorizes fields,
    and returns structured card object with confidence scores.
    """
    lines = clean_text_lines(raw_text)
    
    emails = extract_emails(raw_text)
    phones = extract_phones(raw_text)
    websites = extract_websites(raw_text, emails)
    job_title = extract_job_title(lines)
    company = extract_company(lines, emails, websites, job_title)
    address = extract_address(lines)
    full_name = extract_name(lines, job_title, company, emails)
    
    # Calculate confidence indicators
    confidence = {
        "full_name": "high" if full_name else "low",
        "email": "high" if emails else "low",
        "phone": "high" if phones else "low",
        "job_title": "high" if job_title else "medium",
        "company": "high" if company else "medium",
        "website": "high" if websites else "low",
        "address": "high" if address else "low"
    }
    
    primary_email = emails[0] if emails else ""
    primary_phone = phones[0] if phones else ""
    primary_website = websites[0] if websites else ""
    
    return {
        "full_name": full_name or "",
        "job_title": job_title or "",
        "company": company or "",
        "phone": primary_phone,
        "additional_phones": phones[1:] if len(phones) > 1 else [],
        "email": primary_email,
        "additional_emails": emails[1:] if len(emails) > 1 else [],
        "website": primary_website,
        "address": address or "",
        "raw_text": raw_text,
        "confidence": confidence,
        "lines_count": len(lines)
    }
