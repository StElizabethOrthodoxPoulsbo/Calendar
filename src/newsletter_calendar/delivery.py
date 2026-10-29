"""Send the generated publication through Gmail without logging address secrets."""

import argparse
import os
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from . import parse_month


class DeliveryError(Exception):
    """A safe-to-log configuration or delivery failure."""


def _address(value: str, setting: str) -> str:
    try:
        address = Address(addr_spec=value)
        if not address.username or not address.domain:
            raise ValueError
    except (ValueError, HeaderParseError):
        raise DeliveryError(f"{setting} must contain bare email addresses, not display names.") from None
    return address.addr_spec


@dataclass(frozen=True, repr=False)
class GmailConfig:
    sender: str
    recipients: tuple[str, ...]
    app_password: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "GmailConfig":
        for setting in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD", "CALENDAR_EMAIL_RECIPIENTS"):
            if not environment.get(setting, "").strip():
                raise DeliveryError(f"Missing required GitHub Actions secret: {setting}.")
        sender = _address(environment["GMAIL_SENDER"].strip(), "GMAIL_SENDER")
        if not sender.isascii():
            raise DeliveryError("GMAIL_SENDER must be the full ASCII login email address.")
        recipients = tuple(dict.fromkeys(
            _address(value.strip(), "CALENDAR_EMAIL_RECIPIENTS")
            for value in environment["CALENDAR_EMAIL_RECIPIENTS"].split(",")
        ))
        # Google displays app passwords in space-separated groups.
        password = environment["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
        if not password or not password.isascii() or not password.isprintable():
            raise DeliveryError("GMAIL_APP_PASSWORD must be a Google app password.")
        return cls(sender, recipients, password)


def send_pdf(config: GmailConfig, attachment: Path, month: str) -> None:
    selected = parse_month(month)
    try:
        pdf = attachment.read_bytes()
    except OSError:
        raise DeliveryError("Could not read the generated PDF attachment.") from None
    if not pdf.startswith(b"%PDF-"):
        raise DeliveryError("The generated attachment must be a nonempty PDF.")

    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = "undisclosed-recipients:;"
    message["Subject"] = f"Parish calendar - {selected:%B %Y}"
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = make_msgid()
    message.set_content(
        f"Attached is the parish calendar for {selected:%B %Y}.\n\n"
        "Generated from the parish's public calendar and Orthocal liturgical data. "
        "Please follow parish guidance for fasting.\n"
    )
    message.add_attachment(
        pdf, maintype="application", subtype="pdf",
        filename=f"parish-calendar-{selected:%Y-%m}.pdf",
    )
    try:
        with smtplib.SMTP_SSL(
            "smtp.gmail.com", 465, timeout=30, context=ssl.create_default_context(),
        ) as smtp:
            smtp.login(config.sender, config.app_password)
            refused = smtp.send_message(
                message, from_addr=config.sender, to_addrs=config.recipients,
            )
            if refused:
                raise DeliveryError(
                    "Gmail refused some recipients; others may have received the email. "
                    "No retry was attempted. Check delivery before rerunning."
                )
    except (smtplib.SMTPException, OSError):
        # SMTP errors may embed credentials, addresses, or delivery-server replies.
        raise DeliveryError(
            "Gmail SMTP delivery failed; delivery may be incomplete. "
            "Check Gmail configuration and delivery before rerunning. No retry was attempted."
        ) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Email an already-generated parish PDF via Gmail.")
    parser.add_argument("--attachment", type=Path, required=True)
    parser.add_argument("--month", required=True, help="The generated PDF's month (YYYY-MM).")
    args = parser.parse_args(argv)
    try:
        config = GmailConfig.from_environment(os.environ)
        send_pdf(config, args.attachment, args.month)
    except (DeliveryError, ValueError) as error:
        parser.exit(1, f"Could not email calendar: {error}\n")
    print("Gmail accepted the calendar email for delivery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
