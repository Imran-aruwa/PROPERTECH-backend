"""
PROPERTECH Email Service
Sends transactional emails using SMTP (Gmail / any SMTP provider).
Dev-safe: if SMTP is not configured, logs the email content instead of raising.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Transactional email sender for PROPERTECH."""

    def _send(self, to_email: str, subject: str, html_body: str, text_body: str) -> bool:
        """
        Internal send helper.
        Returns True on success, False (with a log) on failure.
        Never raises — callers must not let email errors break registration / login.
        """
        if not settings.email_configured:
            logger.warning(
                "[EmailService] SMTP not configured — email NOT sent to %s | subject: %s",
                to_email, subject,
            )
            logger.debug("[EmailService] text body:\n%s", text_body)
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
            msg["To"] = to_email

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            smtp_host = settings.SMTP_SERVER
            smtp_port = settings.SMTP_PORT
            smtp_user = settings.SMTP_USER
            smtp_pass = settings.SMTP_PASSWORD

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(msg["From"], [to_email], msg.as_string())

            logger.info("[EmailService] Sent '%s' to %s", subject, to_email)
            return True

        except Exception as exc:
            logger.error("[EmailService] Failed to send '%s' to %s: %s", subject, to_email, exc)
            return False

    # ------------------------------------------------------------------ #
    #  Public methods                                                       #
    # ------------------------------------------------------------------ #

    def send_verification_email(self, to_email: str, user_name: str, verification_token: str) -> bool:
        """Send branded HTML verification email with a 24-hour expiry link."""
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        verify_url = f"{frontend_url}/verify-email?token={verification_token}"
        display_name = user_name or to_email.split("@")[0]

        subject = "Verify your PROPERTECH account"

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Verify Your Email</title>
</head>
<body style="margin:0;padding:0;background:#f0f4ff;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4ff;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background:#2563eb;padding:32px;text-align:center;">
              <div style="display:inline-flex;align-items:center;justify-content:center;
                          width:56px;height:56px;background:rgba(255,255,255,0.2);
                          border-radius:50%;margin-bottom:16px;">
                <span style="color:#ffffff;font-size:28px;font-weight:900;line-height:1;">P</span>
              </div>
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;letter-spacing:-0.5px;">
                PROPERTECH
              </h1>
              <p style="margin:4px 0 0;color:rgba(255,255,255,0.75);font-size:13px;">
                Property Management Platform
              </p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h2 style="margin:0 0 12px;color:#111827;font-size:20px;font-weight:700;">
                Hi {display_name}, verify your email
              </h2>
              <p style="margin:0 0 24px;color:#6b7280;font-size:15px;line-height:1.6;">
                Thank you for creating a PROPERTECH account. Click the button below to verify
                your email address and activate your account.
              </p>
              <div style="text-align:center;margin:32px 0;">
                <a href="{verify_url}"
                   style="display:inline-block;background:#2563eb;color:#ffffff;
                          font-size:15px;font-weight:600;padding:14px 36px;
                          border-radius:8px;text-decoration:none;letter-spacing:0.2px;">
                  Verify My Email
                </a>
              </div>
              <p style="margin:0 0 8px;color:#6b7280;font-size:13px;line-height:1.5;">
                This link expires in <strong>24 hours</strong>. If you did not create an account,
                you can safely ignore this email.
              </p>
              <p style="margin:0;color:#9ca3af;font-size:12px;word-break:break-all;">
                If the button doesn't work, copy and paste this URL into your browser:<br/>
                {verify_url}
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
                &copy; 2025 PROPERTECH SOFTWARE. All rights reserved.<br/>
                Nairobi, Kenya
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        text_body = (
            f"Hi {display_name},\n\n"
            "Please verify your PROPERTECH account by visiting the link below:\n\n"
            f"{verify_url}\n\n"
            "This link expires in 24 hours.\n\n"
            "If you did not create an account, please ignore this email.\n\n"
            "— The PROPERTECH Team"
        )

        return self._send(to_email, subject, html_body, text_body)

    def send_welcome_email(self, to_email: str, user_name: str) -> bool:
        """Send a welcome email after successful email verification."""
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        login_url = f"{frontend_url}/login"
        display_name = user_name or to_email.split("@")[0]

        subject = "Welcome to PROPERTECH — your account is active!"

        html_body = f"""<!DOCTYPE html>
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
               style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:#2563eb;padding:32px;text-align:center;">
              <div style="display:inline-flex;align-items:center;justify-content:center;
                          width:56px;height:56px;background:rgba(255,255,255,0.2);
                          border-radius:50%;margin-bottom:16px;">
                <span style="color:#ffffff;font-size:28px;font-weight:900;line-height:1;">P</span>
              </div>
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">PROPERTECH</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 12px;color:#111827;font-size:22px;font-weight:700;">
                Welcome aboard, {display_name}! 🎉
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
                &copy; 2025 PROPERTECH SOFTWARE. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        text_body = (
            f"Welcome to PROPERTECH, {display_name}!\n\n"
            "Your email has been verified and your account is now active.\n\n"
            f"Log in here: {login_url}\n\n"
            "— The PROPERTECH Team"
        )

        return self._send(to_email, subject, html_body, text_body)


# Singleton
email_service = EmailService()
