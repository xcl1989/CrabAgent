from __future__ import annotations

import logging
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class SmtpError(Exception):
    pass


class SmtpClient:
    """Simple SMTP client for sending emails."""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to: str | None = None,
    ) -> dict:
        """Send an email.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Plain text body
            reply_to: Optional Message-ID to reply to

        Returns:
            dict with status and details
        """
        import smtplib

        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = self.user
            msg["To"] = to

            if reply_to:
                msg["In-Reply-To"] = reply_to
                msg["References"] = reply_to

            if self.port == 465:
                # Direct SSL (QQ Mail, 163, etc.)
                smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
            else:
                # STARTTLS (Gmail, etc.)
                smtp = smtplib.SMTP(self.host, self.port, timeout=30)
                smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
            smtp.quit()

            logger.info(f"Email sent to {to}: {subject}")
            return {"status": "ok", "to": to, "subject": subject}

        except smtplib.SMTPException as e:
            raise SmtpError(f"SMTP error: {e}")
        except OSError as e:
            raise SmtpError(f"Connection error: {e}")
        except Exception as e:
            raise SmtpError(f"Failed to send email: {e}")

    async def send_draft(
        self,
        to: str,
        subject: str,
        body: str,
        draft_id: str | None = None,
    ) -> dict:
        """Send a draft email (same as send, but semantic for draft workflow).

        Returns the same as send().
        """
        return await self.send(to, subject, body)
