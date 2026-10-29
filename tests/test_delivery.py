import contextlib
import io
import os
import smtplib
import tempfile
import textwrap
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from newsletter_calendar import publication_month, write_pdf
from newsletter_calendar.delivery import DeliveryError, GmailConfig, main, send_pdf


ZONE = ZoneInfo("America/Los_Angeles")
SETTINGS = {
    "GMAIL_SENDER": "sender@example.com",
    "GMAIL_APP_PASSWORD": "fake app password",
    "CALENDAR_EMAIL_RECIPIENTS": "first@example.com,second@example.com",
}
WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/generate-calendar.yml"


class DeliveryTests(unittest.TestCase):
    def test_scheduled_next_month_handles_pacific_dst_and_year_rollover(self):
        for month, expected, utc_hour in (
            (3, date(2026, 4, 1), 16),
            (11, date(2026, 12, 1), 17),
            (12, date(2027, 1, 1), 17),
        ):
            now = datetime(2026, month, 21, 9, tzinfo=ZONE)
            self.assertEqual(now.astimezone(ZoneInfo("UTC")).hour, utc_hour)
            with patch("newsletter_calendar.datetime") as clock:
                clock.now.return_value = now
                self.assertEqual(publication_month(None, ZONE), expected)
                clock.now.assert_called_once_with(ZONE)
        self.assertEqual(publication_month("2026-06", ZONE), date(2026, 6, 1))
        for value in ("2026-6", "2026-13", "2026-06\nINJECT=1"):
            with self.assertRaises(ValueError):
                publication_month(value, ZONE)

    @patch("newsletter_calendar.delivery.smtplib.SMTP_SSL")
    def test_attaches_exact_generated_pdf_with_private_envelope_recipients(self, smtp_ssl):
        smtp = smtp_ssl.return_value.__enter__.return_value
        smtp.send_message.return_value = {}
        config = GmailConfig.from_environment(SETTINGS)
        self.assertNotIn(SETTINGS["GMAIL_APP_PASSWORD"], repr(config))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.pdf"
            write_pdf([], path, date(2027, 1, 1), ZONE, "Parish")
            send_pdf(config, path, "2027-01")
            message = smtp.send_message.call_args.args[0]
            attachment, = message.iter_attachments()
            self.assertEqual(attachment.get_content_type(), "application/pdf")
            self.assertEqual(attachment.get_filename(), "parish-calendar-2027-01.pdf")
            self.assertEqual(attachment.get_payload(decode=True), path.read_bytes())
        self.assertEqual(str(message["Subject"]), "Parish calendar - January 2027")
        self.assertIn("January 2027", message.get_body().get_content())
        self.assertEqual(str(message["From"]), SETTINGS["GMAIL_SENDER"])
        self.assertEqual(str(message["To"]), "undisclosed-recipients:;")
        self.assertIsNone(message["Bcc"])
        for recipient in config.recipients:
            self.assertNotIn(recipient, message.as_string())
        smtp.login.assert_called_once_with("sender@example.com", "fakeapppassword")
        self.assertEqual(smtp.send_message.call_args.kwargs, {
            "from_addr": config.sender, "to_addrs": config.recipients,
        })
        smtp.send_message.assert_called_once()
        self.assertEqual(smtp_ssl.call_args.args, ("smtp.gmail.com", 465))
        context = smtp_ssl.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(smtp_ssl.call_args.kwargs["timeout"], 30)

    def test_configuration_rejects_missing_invalid_or_injected_values(self):
        for setting in SETTINGS:
            environment = dict(SETTINGS)
            environment[setting] = ""
            with self.subTest(setting=setting), self.assertRaises(DeliveryError) as error:
                GmailConfig.from_environment(environment)
            self.assertIn(setting, str(error.exception))
        for setting, value in (
            ("GMAIL_SENDER", "Name <sender@example.com>"),
            ("GMAIL_SENDER", "not-an-address"),
            ("GMAIL_SENDER", "sender@example.com\r\nBcc: other@example.com"),
            ("GMAIL_APP_PASSWORD", "non-ascii-\u00e9"),
            ("GMAIL_APP_PASSWORD", "password\ninjection"),
            ("CALENDAR_EMAIL_RECIPIENTS", "first@example.com,"),
            ("CALENDAR_EMAIL_RECIPIENTS", "Name <first@example.com>"),
            ("CALENDAR_EMAIL_RECIPIENTS", "first@example.com;second@example.com"),
        ):
            with self.subTest(setting=setting, value=value):
                with self.assertRaises(DeliveryError) as error:
                    GmailConfig.from_environment({**SETTINGS, setting: value})
                self.assertNotIn(value, str(error.exception))
        config = GmailConfig.from_environment({
            **SETTINGS, "CALENDAR_EMAIL_RECIPIENTS": "first@example.com, first@example.com",
        })
        self.assertEqual(config.recipients, ("first@example.com",))

    @patch("newsletter_calendar.delivery.smtplib.SMTP_SSL")
    def test_missing_non_pdf_and_invalid_month_never_contact_gmail(self, smtp_ssl):
        config = GmailConfig.from_environment(SETTINGS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.pdf"
            with self.assertRaises(DeliveryError):
                send_pdf(config, path, "2026-06")
            path.write_bytes(b"Not a generated PDF")
            with self.assertRaises(DeliveryError):
                send_pdf(config, path, "2026-06")
            with self.assertRaises(ValueError):
                send_pdf(config, path, "2026-13")
        smtp_ssl.assert_not_called()

    @patch("newsletter_calendar.delivery.smtplib.SMTP_SSL")
    def test_failures_are_explicit_redacted_and_never_retried(self, smtp_ssl):
        config = GmailConfig.from_environment(SETTINGS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.pdf"
            write_pdf([], path, date(2026, 6, 1), ZONE, "Parish")
            for failure in ("auth", "partial", "refused", "network", "quit"):
                with self.subTest(failure=failure):
                    smtp_ssl.reset_mock(return_value=True)
                    smtp = smtp_ssl.return_value.__enter__.return_value
                    smtp.send_message.return_value = {}
                    sensitive = b"first@example.com fakeapppassword"
                    if failure == "auth":
                        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, sensitive)
                    elif failure == "partial":
                        smtp.send_message.return_value = {"second@example.com": (550, sensitive)}
                    elif failure == "refused":
                        smtp.send_message.side_effect = smtplib.SMTPRecipientsRefused(
                            {"first@example.com": (550, sensitive)},
                        )
                    elif failure == "network":
                        smtp.send_message.side_effect = OSError(sensitive)
                    else:
                        smtp_ssl.return_value.__exit__.side_effect = OSError(sensitive)
                    stderr, stdout = io.StringIO(), io.StringIO()
                    with patch.dict(os.environ, SETTINGS, clear=True):
                        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                            with self.assertRaises(SystemExit) as error:
                                main(["--attachment", str(path), "--month", "2026-06"])
                    self.assertEqual(error.exception.code, 1)
                    self.assertIn("No retry was attempted", stderr.getvalue())
                    self.assertNotIn("accepted", stdout.getvalue())
                    for secret in (*SETTINGS.values(), "fakeapppassword", "first@example.com"):
                        self.assertNotIn(secret, stderr.getvalue() + stdout.getvalue())
                    self.assertLessEqual(smtp.send_message.call_count, 1)
                    smtp_ssl.assert_called_once()

    @patch("newsletter_calendar.delivery.smtplib.SMTP_SSL")
    def test_missing_secrets_fail_cli_without_smtp(self, smtp_ssl):
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as error:
                main(["--attachment", "dist/calendar.pdf", "--month", "2026-06"])
        self.assertEqual(error.exception.code, 1)
        self.assertIn("GMAIL_SENDER", stderr.getvalue())
        smtp_ssl.assert_not_called()

    @patch("newsletter_calendar.delivery.smtplib.SMTP_SSL")
    def test_successful_cli_logs_acceptance_without_secret_values(self, smtp_ssl):
        smtp_ssl.return_value.__enter__.return_value.send_message.return_value = {}
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.pdf"
            write_pdf([], path, date(2026, 6, 1), ZONE, "Parish")
            with patch.dict(os.environ, SETTINGS, clear=True), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["--attachment", str(path), "--month", "2026-06"]), 0)
        self.assertIn("accepted", stdout.getvalue())
        for value in SETTINGS.values():
            self.assertNotIn(value, stdout.getvalue())

    def test_workflow_schedule_manual_toggle_and_success_only_email_contract(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("cron: '0 9 21 * *'\n      timezone: 'America/Los_Angeles'", workflow)
        self.assertIn(
            "send_email:\n        description:", workflow,
        )
        toggle = workflow.split("      send_email:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("default: false", toggle)
        self.assertIn("type: boolean", toggle)
        condition = (
            "if: success() && (github.event_name == 'schedule' || "
            "(github.event_name == 'workflow_dispatch' && inputs.send_email))"
        )
        self.assertIn(condition, workflow)
        self.assertLess(workflow.index("run: task dev"), workflow.index("actions/upload-artifact"))
        self.assertLess(workflow.index("actions/upload-artifact"), workflow.index(condition))
        self.assertIn('--attachment dist/calendar.pdf --month "$CALENDAR_MONTH"', workflow)
        self.assertNotIn("continue-on-error", workflow)
        for setting in SETTINGS:
            self.assertIn(f"{setting}: ${{{{ secrets.{setting} }}}}", workflow)
        # Execute the workflow's actual month-resolution script, including its
        # GITHUB_ENV handoff, rather than a separate approximation.
        script = workflow.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "env"
            environment = {"CALENDAR_MONTH": "2027-01", "GITHUB_ENV": str(env_file)}
            with patch.dict(os.environ, environment, clear=True):
                exec(compile(textwrap.dedent(script), str(WORKFLOW), "exec"), {})
            self.assertEqual(env_file.read_text(), "CALENDAR_MONTH=2027-01\n")
            with patch.dict(os.environ, {
                **environment, "CALENDAR_MONTH": "",
            }, clear=True), patch("newsletter_calendar.datetime") as clock:
                clock.now.return_value = datetime(2026, 12, 21, 9, tzinfo=ZONE)
                exec(compile(textwrap.dedent(script), str(WORKFLOW), "exec"), {})
            self.assertEqual(
                env_file.read_text(), "CALENDAR_MONTH=2027-01\nCALENDAR_MONTH=2027-01\n",
            )
            with patch.dict(os.environ, {
                **environment, "CALENDAR_MONTH": "2027-01\nINJECT=1",
            }, clear=True):
                with self.assertRaises(ValueError):
                    exec(compile(textwrap.dedent(script), str(WORKFLOW), "exec"), {})
            self.assertEqual(
                env_file.read_text(), "CALENDAR_MONTH=2027-01\nCALENDAR_MONTH=2027-01\n",
            )


if __name__ == "__main__":
    unittest.main()
