import os
import smtplib
from email.mime.text import MIMEText


def send_new_marker_email(marker_title: str, created_by: str):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")

    if not all([host, smtp_user, password]):
        return

    from .database import SessionLocal
    from .models import User
    db = SessionLocal()
    try:
        recipients = [u.email for u in db.query(User).filter(User.notify_email == 1, User.is_approved == 1).all()]
    finally:
        db.close()

    admin_email = os.getenv("ADMIN_EMAIL")
    if admin_email and admin_email not in recipients:
        recipients.append(admin_email)

    if not recipients:
        return

    msg = MIMEText(
        f'Ny vägskada rapporterad av {created_by}: "{marker_title}"\n\n'
        f'Logga in på https://grop.samuelsson.sh för att se den.'
    )
    msg["Subject"] = f"Ny vägskada: {marker_title}"
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(smtp_user, password)
            server.send_message(msg)
    except Exception as e:
        print(f"Email failed: {e}")
