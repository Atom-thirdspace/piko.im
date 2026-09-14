import os
import resend

WELCOME_SUBJECT = "Welcome to Piko: your first problem is waiting"

def _client_ready():
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return False
    resend.api_key = key
    return True

def _welcome_html(name):
    greeting = f"Hey {name}," if name else "Hey,"
    return f"""\
<!doctype html>
<html>
    <body style="margin:0;padding:24px;background:#f6f7f9;
               font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#222;">
    <div style="max-width:520px;margin:0 auto;background:#fff;
                border-radius:12px;padding:32px;">
      <h1 style="margin:0 0 16px;font-size:22px;">{greeting} welcome to Piko 👋</h1>
      <p style="line-height:1.6;margin:0 0 16px;">
        You're in. Piko turns DSA practice into something closer to a game —
        solve problems, earn XP, level up, unlock new topics.
      </p>
      <p style="line-height:1.6;margin:0 0 24px;">
        You're <strong>Level 1</strong> with <strong>0 XP</strong>. Let's fix that.
      </p>
      <a href="https://piko.im"
         style="display:inline-block;background:#ec3750;color:#fff;
                text-decoration:none;padding:12px 22px;border-radius:8px;
                font-weight:600;">Solve your first problem</a>
      <p style="margin:28px 0 0;font-size:13px;color:#888;line-height:1.5;">
        You're getting this because you just signed up at piko.im.
      </p>
    </div>
  </body>
</html>"""

def send_welcome_email(to_email, name=None):
    if not _client_ready():
        return False
    try:
        resend.Emails.send({
            "from": os.environ.get("MAIL_FROM", "Piko <onboarding@resend.dev>"),
            "to": [to_email],
            "subject": WELCOME_SUBJECT,
            "html": _welcome_html(name),
        })
        return True
    except Exception:
        return False