"""Produce a standards-compliant .eml file from a rendered brief.

The .eml can be opened in Outlook, Thunderbird, or Apple Mail and sent
manually — To/CC fields can be edited before dispatch.
"""
from __future__ import annotations
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

from kestrel.models import Brief


def render_eml(
    brief: Brief,
    html_content: str,
    txt_content: str,
    sender: str = "Kestrel <kestrel@kestrel.com.au>",
) -> bytes:
    """Return raw .eml bytes ready for manual dispatch in any email client."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = brief.subject or ""
    msg["From"] = sender
    msg["To"] = ""
    msg["Date"] = (
        formatdate(brief.generated_at.timestamp())
        if brief.generated_at
        else formatdate()
    )

    # Plain text first, HTML second — clients prefer the last matching part
    msg.attach(MIMEText(txt_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    return msg.as_bytes()
