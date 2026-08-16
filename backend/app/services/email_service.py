"""
Free, SMTP-based feedback emails -- no paid email API needed.

Works out of the box with a personal Gmail account:
  1. Turn on 2-Step Verification on the Gmail account that will send mail.
  2. Create an "App Password" (myaccount.google.com/apppasswords) -- a free,
     16-character password scoped just to SMTP, works even though Google
     deprecated plain "less secure apps".
  3. Set these environment variables before starting the backend:
       SMTP_HOST=smtp.gmail.com
       SMTP_PORT=587
       SMTP_USER=your_address@gmail.com
       SMTP_PASS=<the 16-character app password>
       SMTP_FROM_NAME=Toastmasters Club Evaluator
  Any other SMTP provider (Outlook, a club Google Workspace account, etc.)
  works the same way -- just change SMTP_HOST/PORT.

Every email goes ONLY to the single participant whose evaluation it is
(their `Participant.email`), never to a group/all-members list.
"""
import os
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Toastmasters Club Evaluator")


class EmailNotConfigured(RuntimeError):
    pass


def build_feedback_email_body(participant_name: str, speech, evaluation) -> str:
    speech_label = "Table Topics answer" if speech.speech_type == "table_topic" else "prepared speech"
    title = f" ({speech.project_title})" if speech.project_title else ""
    lines = [
        f"Hi {participant_name},",
        "",
        f"Here is your automated evaluation for your {speech_label}{title}:",
        "",
        evaluation.feedback_text,
        "",
        f"Duration: {int(speech.duration_seconds)}s | Pace: {speech.words_per_minute} wpm | "
        f"Filler words: {speech.filler_total} ({speech.filler_rate_per_100_words}/100 words)",
        "",
        "Keep up the great work — every speech is practice toward the next one.",
        "",
        "— Your club's Speech Evaluator tool",
    ]
    return "\n".join(lines)


def send_feedback_email(to_email: str, participant_name: str, speech, evaluation) -> None:
    if not SMTP_USER or not SMTP_PASS:
        raise EmailNotConfigured(
            "SMTP_USER / SMTP_PASS are not set. See services/email_service.py docstring for free Gmail setup."
        )
    if not to_email:
        raise ValueError("This participant has no email address on file.")

    body = build_feedback_email_body(participant_name, speech, evaluation)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Your Toastmasters speech evaluation"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())
