import html
import re
from typing import Dict, Any

def render_public_card_html(card: Dict[str, Any], auto_download: bool = False) -> str:
    full_name = html.escape(card.get("full_name") or "Contact")
    job_title = html.escape(card.get("job_title") or "")
    company = html.escape(card.get("company") or "")
    badge_text = html.escape(card.get("badge_text") or "")
    headline = html.escape(card.get("headline") or "")
    bio = html.escape(card.get("bio") or "")
    phone = (card.get("phone") or "").strip()
    email = (card.get("email") or "").strip()
    website = (card.get("website") or "").strip()
    address = (card.get("address") or "").strip()
    slug = html.escape(card.get("slug") or "card")
    theme = card.get("theme") or "apple_dark"

    # Monogram / initials
    name_parts = full_name.split()
    initials = "".join(p[0].upper() for p in name_parts[:2]) if name_parts else "C"

    # Theme color palettes
    themes = {
        "apple_dark": {
            "bg": "#0B0C10",
            "card_bg": "rgba(28, 28, 30, 0.75)",
            "border": "rgba(255, 255, 255, 0.12)",
            "accent": "#0071E3",
            "accent_glow": "rgba(0, 113, 227, 0.35)",
            "text": "#FFFFFF",
            "subtext": "#86868B",
            "pill_bg": "rgba(255, 255, 255, 0.08)",
        },
        "midnight_blue": {
            "bg": "#050B14",
            "card_bg": "rgba(11, 25, 44, 0.8)",
            "border": "rgba(64, 156, 255, 0.25)",
            "accent": "#0A84FF",
            "accent_glow": "rgba(10, 132, 255, 0.4)",
            "text": "#FFFFFF",
            "subtext": "#99B4D6",
            "pill_bg": "rgba(10, 132, 255, 0.12)",
        },
        "obsidian_gold": {
            "bg": "#0D0B08",
            "card_bg": "rgba(26, 22, 16, 0.85)",
            "border": "rgba(255, 214, 10, 0.25)",
            "accent": "#D4AF37",
            "accent_glow": "rgba(212, 175, 55, 0.4)",
            "text": "#FFFDF7",
            "subtext": "#B3A48A",
            "pill_bg": "rgba(212, 175, 55, 0.12)",
        },
        "emerald_pro": {
            "bg": "#040D08",
            "card_bg": "rgba(13, 31, 23, 0.85)",
            "border": "rgba(48, 209, 88, 0.25)",
            "accent": "#28CD41",
            "accent_glow": "rgba(40, 205, 65, 0.4)",
            "text": "#FFFFFF",
            "subtext": "#8CA895",
            "pill_bg": "rgba(40, 205, 65, 0.12)",
        },
    }
    t = themes.get(theme, themes["apple_dark"])
    clean_digits = re.sub(r"[^\d+]", "", phone)

    buttons_html = []
    # Primary Call
    if phone:
        buttons_html.append(f'''
            <a href="tel:{html.escape(phone)}" class="action-btn">
                <span class="icon">📞</span>
                <span class="label">Call</span>
            </a>
        ''')
        # WhatsApp
        buttons_html.append(f'''
            <a href="https://wa.me/{clean_digits.lstrip('+')}" target="_blank" rel="noopener" class="action-btn">
                <span class="icon">💬</span>
                <span class="label">WhatsApp</span>
            </a>
        ''')
    if email:
        buttons_html.append(f'''
            <a href="mailto:{html.escape(email)}" class="action-btn">
                <span class="icon">✉️</span>
                <span class="label">Email</span>
            </a>
        ''')
    if website:
        web_url = website if website.startswith(('http://', 'https://')) else 'https://' + website
        buttons_html.append(f'''
            <a href="{html.escape(web_url)}" target="_blank" rel="noopener" class="action-btn">
                <span class="icon">🌐</span>
                <span class="label">Website</span>
            </a>
        ''')

    actions_grid = "".join(buttons_html)

    auto_script = ""
    if auto_download:
        auto_script = """
        <script>
            window.addEventListener('DOMContentLoaded', () => {
                setTimeout(() => {
                    window.location.href = window.location.pathname.replace(/\\/?$/, '/vcard');
                }, 400);
            });
        </script>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>{full_name} | Digital Business Card</title>
    <meta name="description" content="Connect with {full_name} ({job_title} at {company}). Add directly to your phone contacts.">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📇</text></svg>">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }}
        body {{
            background-color: {t['bg']};
            color: {t['text']};
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            min-height: 100vh;
            min-height: 100dvh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: calc(env(safe-area-inset-top) + 20px) 16px calc(env(safe-area-inset-bottom) + 24px) 16px;
            background-image: radial-gradient(circle at 50% 10%, {t['accent_glow']} 0%, transparent 55%);
            background-repeat: no-repeat;
        }}
        .card {{
            width: 100%;
            max-width: 420px;
            background: {t['card_bg']};
            backdrop-filter: blur(28px) saturate(180%);
            -webkit-backdrop-filter: blur(28px) saturate(180%);
            border: 1px solid {t['border']};
            border-radius: 28px;
            padding: 32px 24px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.15);
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            position: relative;
            overflow: hidden;
        }}
        .avatar {{
            width: 80px;
            height: 80px;
            border-radius: 50%;
            background: linear-gradient(135deg, {t['accent']}, #5856D6);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
            font-weight: 700;
            color: #FFFFFF;
            margin-bottom: 18px;
            box-shadow: 0 10px 24px {t['accent_glow']};
            border: 2px solid rgba(255, 255, 255, 0.2);
        }}
        .badge {{
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
            padding: 4px 10px;
            border-radius: 12px;
            background: {t['pill_bg']};
            color: {t['accent']};
            border: 1px solid {t['border']};
            margin-bottom: 12px;
        }}
        h1 {{
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.4px;
            margin-bottom: 4px;
        }}
        .title-company {{
            font-size: 14px;
            font-weight: 500;
            color: {t['subtext']};
            margin-bottom: 14px;
            line-height: 1.4;
        }}
        .headline {{
            font-size: 13px;
            color: {t['subtext']};
            line-height: 1.5;
            margin-bottom: 24px;
            padding: 0 10px;
        }}
        /* Save Contact Hero Button */
        .save-vcard-btn {{
            width: 100%;
            background: {t['accent']};
            color: #FFFFFF;
            text-decoration: none;
            font-size: 15px;
            font-weight: 600;
            padding: 16px 20px;
            border-radius: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            box-shadow: 0 8px 24px {t['accent_glow']};
            transition: transform 0.15s ease, opacity 0.15s ease;
            margin-bottom: 20px;
        }}
        .save-vcard-btn:active {{
            transform: scale(0.97);
            opacity: 0.9;
        }}
        /* Actions grid */
        .actions-grid {{
            width: 100%;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(75px, 1fr));
            gap: 10px;
            margin-bottom: 20px;
        }}
        .action-btn {{
            background: {t['pill_bg']};
            border: 1px solid {t['border']};
            border-radius: 14px;
            padding: 12px 6px;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 6px;
            color: {t['text']};
            text-decoration: none;
            font-size: 11px;
            font-weight: 500;
            transition: background 0.15s ease;
        }}
        .action-btn:active {{
            background: rgba(255, 255, 255, 0.15);
        }}
        .action-btn .icon {{
            font-size: 18px;
        }}
        /* Contact info list */
        .info-list {{
            width: 100%;
            text-align: left;
            border-top: 1px solid {t['border']};
            padding-top: 16px;
            font-size: 12px;
            color: {t['subtext']};
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .info-row {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .info-row span {{
            word-break: break-all;
        }}
        /* Footer */
        .footer {{
            margin-top: 24px;
            font-size: 11px;
            color: rgba(255, 255, 255, 0.35);
            display: flex;
            align-items: center;
            gap: 6px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="avatar">{initials}</div>
        {f'<div class="badge">{badge_text}</div>' if badge_text else ''}
        <h1>{full_name}</h1>
        <div class="title-company">
            {job_title}{f' &bull; {company}' if company and job_title else company}
        </div>
        {f'<div class="headline">{headline}</div>' if headline else ''}

        <!-- Primary Call To Action: Direct vCard Add -->
        <a href="/c/{slug}/vcard" download class="save-vcard-btn" id="saveContactBtn">
            <span>📥 Save Contact to Phone</span>
        </a>

        <!-- Quick Actions -->
        <div class="actions-grid">
            {actions_grid}
        </div>

        <!-- Detail rows -->
        <div class="info-list">
            {f'<div class="info-row"><span>📞 {html.escape(phone)}</span></div>' if phone else ''}
            {f'<div class="info-row"><span>✉️ {html.escape(email)}</span></div>' if email else ''}
            {f'<div class="info-row"><span>🌐 {html.escape(website)}</span></div>' if website else ''}
            {f'<div class="info-row"><span>📍 {html.escape(address)}</span></div>' if address else ''}
        </div>
    </div>

    <div class="footer">
        <span>⚡ Powered by Cardr Studio &bull; Conference QR</span>
    </div>

    {auto_script}
</body>
</html>
"""
