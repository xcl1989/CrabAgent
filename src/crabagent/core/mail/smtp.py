from __future__ import annotations

import logging
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path

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
        attachments: list[str] | None = None,
        html: bool = False,
    ) -> dict:
        """Send an email, optionally with file attachments.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Email body (plain text or HTML if ``html=True``).
            reply_to: Optional Message-ID to reply to.
            attachments: List of file paths to attach.
            html: If True, body is treated as HTML.

        Returns:
            dict with status and details.
        """
        import smtplib

        try:
            has_attachments = attachments and len(attachments) > 0

            if has_attachments:
                # Use MIMEMultipart for mixed content + attachments
                msg = MIMEMultipart()
                msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
            else:
                if html:
                    msg = MIMEMultipart("alternative")
                    msg.attach(MIMEText(body, "html", "utf-8"))
                else:
                    msg = MIMEText(body, "plain", "utf-8")

            msg["Subject"] = subject
            msg["From"] = self.user
            msg["To"] = to
            msg["Date"] = formatdate(localtime=True)

            if reply_to:
                msg["In-Reply-To"] = reply_to
                msg["References"] = reply_to

            # Attach files
            if has_attachments:
                for file_path_str in attachments:
                    p = Path(file_path_str)
                    if not p.exists():
                        logger.warning(f"Attachment not found: {p}")
                        continue
                    # Guess MIME type
                    import mimetypes
                    mime_type, _ = mimetypes.guess_type(str(p))
                    if mime_type is None:
                        mime_type = "application/octet-stream"
                    main_type, sub_type = mime_type.split("/", 1)

                    with open(p, "rb") as f:
                        part = MIMEBase(main_type, sub_type)
                        part.set_payload(f.read())

                    # Encode payload in base64
                    from email import encoders
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f'attachment; filename="{p.name}"',
                    )
                    msg.attach(part)
                    logger.info(f"Attached: {p.name} ({p.stat().st_size} bytes)")

            if self.port == 465:
                smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
            else:
                smtp = smtplib.SMTP(self.host, self.port, timeout=30)
                smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
            smtp.quit()

            att_count = len(attachments) if attachments else 0
            logger.info(f"Email sent to {to}: {subject} ({att_count} attachments)")
            return {"status": "ok", "to": to, "subject": subject, "attachments": att_count}

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
        attachments: list[str] | None = None,
    ) -> dict:
        """Send a draft email (same as send, but semantic for draft workflow).

        Returns the same as send().
        """
        return await self.send(to, subject, body, attachments=attachments)
