import os

import resend
from markupsafe import escape

WELCOME_SUBJECT = "Welcome to Piko: your first problem is waiting"
VERIFY_SUBJECT = "Confirm your email for Piko"
LOGIN_ALERT_SUBJECT = "New sign-in to your Piko account"

BRAND = "#ec3750"


def _client_ready():
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return False
    resend.api_key = key
    return True


def _layout(heading, body_html, cta=None, footer=""):
    button = ""
    if cta is not None:
        label, href = cta
        button = (f'<a href="{href}" style="display:inline-block;background:{BRAND};'
                  'color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;'
                  f'font-weight:600;">{label}</a>')
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f6f7f9;
               font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#222;">
    <div style="max-width:520px;margin:0 auto;background:#fff;
                border-radius:12px;padding:32px;">
      <h1 style="margin:0 0 16px;font-size:22px;">{heading}</h1>
      {body_html}
      {button}
      <p style="margin:28px 0 0;font-size:13px;color:#888;line-height:1.5;">{footer}</p>
    </div>
  </body>
</html>"""


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


def _greeting(name):
    return f"Hey {escape(name)}," if name else "Hey,"


_INTRO = """\
      <p style="line-height:1.6;margin:0 0 16px;">
        You're in. Piko turns DSA practice into something closer to a game &mdash;
        solve problems, earn XP, level up, unlock new topics.
      </p>
      <p style="line-height:1.6;margin:0 0 24px;">
        You're <strong>Level 1</strong> with <strong>0 XP</strong>. Let's fix that.
      </p>"""


def send_welcome_email(to_email, name=None):
    """For signups where the provider already vouched for the address."""
    return _send(to_email, WELCOME_SUBJECT, _layout(
        f"{_greeting(name)} welcome to Piko 👋",
        _INTRO,
        cta=("Solve your first problem", "https://piko.im"),
        footer="You're getting this because you just signed up at piko.im.",
    ))


def send_verification_email(to_email, verify_url, name=None, welcome=False):
    if welcome:
        heading = f"{_greeting(name)} welcome to Piko 👋"
        body = _INTRO + """
      <p style="line-height:1.6;margin:0 0 24px;">
        One thing first: confirm this is your email address.
      </p>"""
    else:
        heading = f"{_greeting(name)} confirm your email"
        body = """
      <p style="line-height:1.6;margin:0 0 24px;">
        Tap the button to confirm this address belongs to your Piko account.
      </p>"""
    return _send(to_email, WELCOME_SUBJECT if welcome else VERIFY_SUBJECT, _layout(
        heading, body,
        cta=("Confirm my email", verify_url),
        footer=("This link works for 24 hours. If you didn't sign up for Piko, "
                "ignore this email and nothing happens."),
    ))


def send_login_alert_email(to_email, name, when, ip, user_agent, settings_url):
    body = f"""
      <p style="line-height:1.6;margin:0 0 16px;">
        Your Piko account was just signed in to from a device we haven't seen before.
      </p>
      <table style="font-size:14px;line-height:1.8;margin:0 0 24px;color:#444;">
        <tr><td style="padding-right:12px;color:#888;">When</td>
            <td>{when.strftime('%d %b %Y, %H:%M UTC')}</td></tr>
        <tr><td style="padding-right:12px;color:#888;">IP</td>
            <td>{escape(ip)}</td></tr>
        <tr><td style="padding-right:12px;color:#888;">Browser</td>
            <td>{escape(user_agent)}</td></tr>
      </table>
      <p style="line-height:1.6;margin:0 0 24px;">
        That was probably you. If it wasn't, change your password now.
      </p>"""
    return _send(to_email, LOGIN_ALERT_SUBJECT, _layout(
        f"{_greeting(name)} new sign-in", body,
        cta=("Review my account", settings_url),
        footer="We send this once per new device, not on every sign-in.",
    ))
