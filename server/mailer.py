import os

import resend
from flask import render_template

WELCOME_SUBJECT = "Welcome to Piko: your first problem is waiting"
VERIFY_SUBJECT = "Confirm your email for Piko"
LOGIN_ALERT_SUBJECT = "New sign-in to your Piko account"


def _client_ready():
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return False
    resend.api_key = key
    return True


def _send(to_email, subject, html):
    if not _client_ready():
        return False
    try:
        resend.Emails.send({
            "from": os.environ.get("MAIL_FROM", "Piko <onboarding@resend.dev>"),
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
        return True
    except Exception:
        return False


def send_welcome_email(to_email, name=None):
    """For signups where the provider already vouched for the address."""
    html = render_template(
        "emails/authentication.html",
        name=name,
        welcome=True,
        verify_url=None,
        cta_url="https://piko.im",
        cta_label="Solve your first problem",
    )
    return _send(to_email, WELCOME_SUBJECT, html)


def send_verification_email(to_email, verify_url, name=None, welcome=False):
    html = render_template(
        "emails/authentication.html",
        name=name,
        welcome=welcome,
        verify_url=verify_url,
        cta_url=verify_url,
        cta_label="Confirm my email",
    )
    subject = WELCOME_SUBJECT if welcome else VERIFY_SUBJECT
    return _send(to_email, subject, html)


def send_login_alert_email(to_email, name, when, ip, user_agent, settings_url):
    html = render_template(
        "emails/new-login.html",
        name=name,
        when=when.strftime("%d %b %Y, %H:%M UTC"),
        ip=ip,
        user_agent=user_agent,
        settings_url=settings_url,
    )
    return _send(to_email, LOGIN_ALERT_SUBJECT, html)
