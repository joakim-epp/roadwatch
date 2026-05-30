import os
import resend

API_KEY = os.getenv("RESEND_API_KEY")
FROM_ADDR = os.getenv("RESET_EMAIL_FROM", "Grop <noreply@robot.samuelsson.sh>")
APP_URL = os.getenv("APP_URL", "https://grop.samuelsson.sh")


def send_password_reset(to_email: str, name: str, token: str) -> bool:
    if not API_KEY:
        print("RESEND_API_KEY not set — skipping password reset email")
        return False
    resend.api_key = API_KEY
    link = f"{APP_URL}/reset?token={token}"
    greeting = name or "där"
    html = f"""\
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:480px;margin:0 auto;padding:24px;color:#1f2937">
  <h2 style="color:#0f172a;margin:0 0 16px">Återställ ditt lösenord</h2>
  <p>Hej {greeting},</p>
  <p>Klicka på länken nedan för att välja ett nytt lösenord. Länken gäller i 1 timme.</p>
  <p style="margin:24px 0">
    <a href="{link}" style="background:#3b82f6;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600;display:inline-block">
      Återställ lösenord
    </a>
  </p>
  <p style="font-size:13px;color:#64748b">Eller kopiera länken: <br><a href="{link}" style="color:#3b82f6;word-break:break-all">{link}</a></p>
  <p style="font-size:13px;color:#64748b;margin-top:24px">Om du inte begärde detta kan du ignorera mejlet — ditt lösenord ändras inte.</p>
</div>"""
    try:
        resend.Emails.send({
            "from": FROM_ADDR,
            "to": to_email,
            "subject": "Återställ ditt Grop-lösenord",
            "html": html,
        })
        return True
    except Exception as e:
        print(f"Resend send failed: {e}")
        return False
