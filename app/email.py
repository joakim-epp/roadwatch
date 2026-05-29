import os
import smtplib
from email.mime.text import MIMEText


def send_new_marker_email(marker_title: str, created_by: str):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    admin_email = os.getenv("ADMIN_EMAIL")

    if not all([host, user, password, admin_email]):
        return

    msg = MIMEText(
        f'Ny vägskada rapporterad av {created_by}: "{marker_title}"\n\n'
        f'Logga in på https://grop.samuelsson.sh för att se den.'
    )
    msg["Subject"] = f"Ny vägskada: {marker_title}"
    msg["From"] = user
    msg["To"] = admin_email

    try:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
    except Exception as e:
        print(f"Email failed: {e}")
