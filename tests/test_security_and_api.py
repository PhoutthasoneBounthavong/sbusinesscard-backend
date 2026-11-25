import sys
import os
import unittest
import io
import asyncio
from fastapi import UploadFile, HTTPException

# Add parent dir to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.vcard_service import generate_vcard_content, escape_vcard_val
from app.main import (
    sanitize_filename,
    sanitize_csv_cell,
    ALLOWED_IMAGE_EXTENSIONS,
    scan_business_card,
    create_card,
    get_card,
    delete_card,
    download_card_vcard,
    export_cards_csv,
    CardCreateRequest,
    CardUpdateRequest,
    update_card,
)

class TestSecurityAndFunctionality(unittest.TestCase):
    def test_vcard_crlf_injection_prevention(self):
        """Verify that CRLF injections inside name, company, or title are neutralized."""
        malicious_card = {
            "full_name": "Injected Name\r\nTEL;TYPE=CELL:+19999999999\r\nNOTE:Hacked",
            "company": "Evil Corp\r\nURL:http://evil.com",
            "job_title": "CEO\r\nROLE:Admin",
            "phone": "+1 (555) 123-4567\r\nX-INJECTED:Bad",
            "email": "test@example.com\r\nX-INJECTED:Bad",
            "notes": "First line\nSecond line"
        }
        vcard = generate_vcard_content(malicious_card)
        
        # Verify no unescaped CRLF injections in single-line properties
        lines = [line.strip() for line in vcard.split("\r\n") if line.strip()]
        for line in lines:
            self.assertFalse(line.startswith("TEL;TYPE=CELL:+19999999999"), "CRLF injected TEL found!")
            self.assertFalse(line.startswith("URL:http://evil.com"), "CRLF injected URL found!")
            self.assertFalse(line.startswith("ROLE:Admin"), "CRLF injected ROLE found!")

    def test_filename_header_sanitization(self):
        """Verify filenames used in Content-Disposition cannot perform header splitting or quote breakouts."""
        dangerous_names = [
            'test"file.vcf',
            'john\r\nX-Injected-Header: evil',
            '../../etc/passwd',
            'Jane Doe #1'
        ]
        for name in dangerous_names:
            safe = sanitize_filename(name)
            self.assertNotIn('"', safe)
            self.assertNotIn('\r', safe)
            self.assertNotIn('\n', safe)
            self.assertNotIn('/', safe)
            self.assertNotIn('\\', safe)

    def test_csv_formula_injection_prevention(self):
        """Verify that spreadsheet formulas starting with =, +, -, @ are escaped with single quote."""
        self.assertEqual(sanitize_csv_cell("=CMD|' /C calc'!A0"), "'=CMD|' /C calc'!A0")
        self.assertEqual(sanitize_csv_cell("+12345"), "'+12345")
        self.assertEqual(sanitize_csv_cell("-100"), "'-100")
        self.assertEqual(sanitize_csv_cell("@SUM(A1:A10)"), "'@SUM(A1:A10)")
        self.assertEqual(sanitize_csv_cell("Normal Name"), "Normal Name")
        self.assertEqual(sanitize_csv_cell(None), "")

    def test_upload_extension_whitelist(self):
        """Verify that non-image file uploads (.html, .svg, .exe, .sh) are rejected with 400 Bad Request."""
        bad_files = [
            ("malicious.html", b"<html><script>alert(1)</script></html>"),
            ("payload.exe", b"MZ\x90\x00\x03\x00\x00\x00"),
            ("vector.svg", b"<svg onload=alert(1)>"),
            ("script.sh", b"#!/bin/bash\nrm -rf /"),
        ]

        from fastapi import BackgroundTasks
        for filename, data in bad_files:
            upload = UploadFile(filename=filename, file=io.BytesIO(data))
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(scan_business_card(background_tasks=BackgroundTasks(), file=upload))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Unsupported file format", ctx.exception.detail)

    def test_crud_and_vcard_endpoints(self):
        """Verify CRUD and sanitization in endpoints directly."""
        mock_user = {"user_id": 1, "role": "super_admin", "status": "active"}
        card_req = CardCreateRequest(
            full_name="Sarah Connor",
            company="Cyberdyne Systems",
            job_title="Security Officer",
            email="sarah@resistance.org",
            phone="+1 555-0199"
        )
        created = create_card(card_req, current_user=mock_user)
        self.assertTrue(created["success"])
        card_id = created["card"]["id"]

        # Fetch
        fetched = get_card(card_id, current_user=mock_user)
        self.assertEqual(fetched["card"]["full_name"], "Sarah Connor")

        # Update
        update_req = CardUpdateRequest(job_title="Chief Security Officer")
        updated = update_card(card_id, update_req, current_user=mock_user)
        self.assertEqual(updated["card"]["job_title"], "Chief Security Officer")

        # Download vCard
        vcard_resp = download_card_vcard(card_id, current_user=mock_user)
        self.assertEqual(vcard_resp.status_code, 200)
        self.assertIn("BEGIN:VCARD", vcard_resp.body.decode("utf-8"))
        self.assertIn("Cyberdyne Systems", vcard_resp.body.decode("utf-8"))

        # Clean up
        deleted = delete_card(card_id, current_user=mock_user)
        self.assertTrue(deleted["success"])

    def test_admin_rbac_security(self):
        """Verify that admin endpoints strictly reject non-admin users."""
        from app.auth_service import require_admin
        from app.main import admin_get_overview, admin_list_users

        # 1. Non-admin user gets 403 Forbidden
        from app.auth_service import create_access_token
        normal_token = create_access_token(user_id=999, email="hacker@test.com", full_name="Hacker", role="user")
        with self.assertRaises(HTTPException) as ctx:
            require_admin(authorization=f"Bearer {normal_token}")
        self.assertEqual(ctx.exception.status_code, 403)

        # 2. Super admin succeeds
        admin_token = create_access_token(user_id=1, email="demo@cardr.app", full_name="Admin", role="super_admin")
        valid_admin = require_admin(authorization=f"Bearer {admin_token}")
        self.assertEqual(valid_admin["role"], "super_admin")

        # 3. Overview returns metrics when admin
        overview = admin_get_overview(admin_user=valid_admin)
        self.assertIn("metrics", overview)
        self.assertIn("total_users", overview["metrics"])

if __name__ == "__main__":
    unittest.main()
