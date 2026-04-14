"""
PROPERTECH Email Service
Sends transactional emails using SMTP (Gmail / any SMTP provider).
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── SMTP config — checks all common env var naming conventions ───────────────
SMTP_HOST = (
    os.environ.get("SMTP_HOST")
    or os.environ.get("SMTP_SERVER")
    or os.environ.get("MAIL_SERVER")
    or "smtp.gmail.com"
)
SMTP_PORT = int(
    os.environ.get("SMTP_PORT")
    or os.environ.get("MAIL_PORT")
    or 587
)
SMTP_USER = (
    os.environ.get("SMTP_USER")
    or os.environ.get("SMTP_USERNAME")
    or os.environ.get("MAIL_USERNAME")
    or ""
)
SMTP_PASSWORD = (
    os.environ.get("SMTP_PASSWORD")
    or os.environ.get("MAIL_PASSWORD")
    or ""
)
SMTP_FROM_EMAIL = (
    os.environ.get("SMTP_FROM_EMAIL")
    or os.environ.get("FROM_EMAIL")
    or os.environ.get("MAIL_FROM")
    or SMTP_USER
)
SMTP_FROM_NAME = (
    os.environ.get("SMTP_FROM_NAME")
    or "ProperTech Software"
)
FRONTEND_URL = (
    os.environ.get("FRONTEND_URL")
    or "https://propertechsoftware.co.ke"
)

# Lazy-load from pydantic settings as fallback if env vars are empty
def _load_from_settings() -> None:
    """Pull SMTP values from pydantic settings into module globals if still unset."""
    global SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_FROM_NAME, FRONTEND_URL
    try:
        from app.core.config import settings
        if not SMTP_USER:
            SMTP_USER = settings.SMTP_USER or ""
        if not SMTP_PASSWORD:
            SMTP_PASSWORD = settings.SMTP_PASSWORD or ""
        if SMTP_HOST == "smtp.gmail.com" and settings.SMTP_SERVER:
            SMTP_HOST = settings.SMTP_SERVER
        if not SMTP_FROM_EMAIL or SMTP_FROM_EMAIL == SMTP_USER:
            SMTP_FROM_EMAIL = settings.SMTP_FROM_EMAIL or SMTP_USER
        if SMTP_FROM_NAME == "ProperTech Software" and settings.SMTP_FROM_NAME:
            SMTP_FROM_NAME = settings.SMTP_FROM_NAME
        if FRONTEND_URL == "https://propertechsoftware.co.ke" and settings.FRONTEND_URL:
            FRONTEND_URL = settings.FRONTEND_URL
    except Exception:
        pass


# ── Core send function ────────────────────────────────────────────────────────

def send_email(to_email: str, subject: str, html_content: str) -> bool:
    """Send an HTML email. Returns True on success, False on failure."""
    _load_from_settings()

    print(f"[EMAIL] Attempting to send to {to_email}")
    print(f"[EMAIL] SMTP_HOST={SMTP_HOST}, SMTP_PORT={SMTP_PORT}")
    print(f"[EMAIL] SMTP_USER={SMTP_USER}")
    print(f"[EMAIL] FROM={SMTP_FROM_EMAIL}")

    if not SMTP_USER or not SMTP_PASSWORD:
        print("[EMAIL ERROR] SMTP_USER or SMTP_PASSWORD not configured!")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = to_email

        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())

        print(f"[EMAIL] Successfully sent to {to_email}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print(f"[EMAIL ERROR] Authentication failed — check SMTP_USER and SMTP_PASSWORD: {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"[EMAIL ERROR] SMTP error: {e}")
        return False
    except Exception as e:
        print(f"[EMAIL ERROR] Unexpected error: {e}")
        return False


# ── Transactional email helpers ───────────────────────────────────────────────

def send_verification_email(to_email: str, token: str) -> bool:
    """Send a branded verification email with a 24-hour expiry link."""
    _load_from_settings()
    verify_url = f"{FRONTEND_URL.rstrip('/')}/verify-email?token={token}"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Verify your ProperTech account</title>
</head>
<body style="margin:0;padding:0;background:#f0f4ff;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4ff;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 20px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:#2563eb;padding:32px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">
                PROPERTECH
              </h1>
              <p style="margin:4px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">
                Property Management Platform
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="margin:0 0 12px;color:#111827;font-size:20px;font-weight:700;">
                Verify your email address
              </h2>
              <p style="margin:0 0 24px;color:#6b7280;font-size:15px;line-height:1.6;">
                Thank you for signing up! Please verify your email address to activate
                your account and start managing your properties.
              </p>
              <div style="text-align:center;margin:32px 0;">
                <a href="{verify_url}"
                   style="display:inline-block;background:#2563eb;color:#ffffff;
                          font-size:15px;font-weight:600;padding:14px 36px;
                          border-radius:8px;text-decoration:none;">
                  Verify My Email
                </a>
              </div>
              <p style="margin:0 0 8px;color:#6b7280;font-size:13px;">
                Or copy and paste this link into your browser:
              </p>
              <p style="margin:0;color:#6366f1;font-size:13px;word-break:break-all;">
                {verify_url}
              </p>
              <p style="margin:24px 0 0;color:#9ca3af;font-size:13px;text-align:center;">
                This link expires in <strong>24 hours</strong>. If you did not create an
                account, please ignore this email.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
                &copy; 2026 ProperTech Software. All rights reserved.<br/>
                Modern property management for Kenyan landlords and agents.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return send_email(
        to_email=to_email,
        subject="Verify your ProperTech account",
        html_content=html_content,
    )


def send_welcome_email(to_email: str, user_name: str = "") -> bool:
    """Send a welcome email after successful email verification."""
    _load_from_settings()
    login_url = f"{FRONTEND_URL.rstrip('/')}/login"
    display_name = user_name or to_email.split("@")[0]

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Welcome to PROPERTECH</title>
</head>
<body style="margin:0;padding:0;background:#f0f4ff;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4ff;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 20px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:#2563eb;padding:32px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">PROPERTECH</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 12px;color:#111827;font-size:22px;font-weight:700;">
                Welcome aboard, {display_name}!
              </h2>
              <p style="margin:0 0 20px;color:#6b7280;font-size:15px;line-height:1.6;">
                Your email has been verified and your PROPERTECH account is now fully active.
                You can now sign in and start managing your properties.
              </p>
              <div style="text-align:center;margin:28px 0;">
                <a href="{login_url}"
                   style="display:inline-block;background:#2563eb;color:#ffffff;
                          font-size:15px;font-weight:600;padding:14px 36px;
                          border-radius:8px;text-decoration:none;">
                  Go to Dashboard
                </a>
              </div>
            </td>
          </tr>
          <tr>
            <td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
                &copy; 2026 ProperTech Software. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return send_email(
        to_email=to_email,
        subject="Welcome to PROPERTECH — your account is active!",
        html_content=html_content,
    )


def send_password_reset_email(to_email: str, token: str) -> bool:
    """Send a password reset email with a 1-hour expiry link."""
    _load_from_settings()
    reset_url = f"{FRONTEND_URL.rstrip('/')}/reset-password?token={token}"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Reset your PROPERTECH password</title>
</head>
<body style="margin:0;padding:0;background:#f0f4ff;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4ff;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 20px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:#2563eb;padding:32px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">PROPERTECH</h1>
              <p style="margin:4px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">Property Management Platform</p>
            </td>
          </tr>
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="margin:0 0 12px;color:#111827;font-size:20px;font-weight:700;">Reset your password</h2>
              <p style="margin:0 0 24px;color:#6b7280;font-size:15px;line-height:1.6;">
                We received a request to reset your password. Click the button below to set a new password.
                If you did not request this, please ignore this email — your password will remain unchanged.
              </p>
              <div style="text-align:center;margin:32px 0;">
                <a href="{reset_url}"
                   style="display:inline-block;background:#2563eb;color:#ffffff;
                          font-size:15px;font-weight:600;padding:14px 36px;
                          border-radius:8px;text-decoration:none;">
                  Reset My Password
                </a>
              </div>
              <p style="margin:0 0 8px;color:#6b7280;font-size:13px;">Or copy and paste this link into your browser:</p>
              <p style="margin:0;color:#6366f1;font-size:13px;word-break:break-all;">{reset_url}</p>
              <p style="margin:24px 0 0;color:#9ca3af;font-size:13px;text-align:center;">
                This link expires in <strong>1 hour</strong>.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
                &copy; 2026 ProperTech Software. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return send_email(
        to_email=to_email,
        subject="Reset your PROPERTECH password",
        html_content=html_content,
    )


# ── Legacy class wrapper so any code importing `email_service` still works ───

class _EmailServiceCompat:
    """Thin compatibility shim — delegates to module-level functions."""

    def send_verification_email(self, to_email: str, user_name: str = "", verification_token: str = "") -> bool:
        return send_verification_email(to_email, verification_token)

    def send_welcome_email(self, to_email: str, user_name: str = "") -> bool:
        return send_welcome_email(to_email, user_name)

    def _send(self, to_email: str, subject: str, html_body: str, text_body: str) -> bool:
        return send_email(to_email, subject, html_body)


email_service = _EmailServiceCompat()
