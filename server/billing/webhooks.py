import base64
import hashlib
import hmac
import time

TOLERANCE_SECONDS = 5 * 60

class WebhookError(Exception):
    """The delivery is not provably from Polar. Answer 403 and move on."""


def _key(secret):
    secret = (secret or "").strip()
    if not secret:
        raise WebhookError("no webhook secret configured")
    if secret.startswith("whsec_"):
        return base64.b64decode(secret[len("whsec_"):])
    return secret.encode("utf-8")

def _signatures(header):
    out = []
    for part in (header or "").split():
        version, _, value = part.partition(",")
        if version == "v1" and value:
            out.append(value)
    return out

def verify(body, headers, secret, now=None):

    event_id = headers.get("webhook-id") or ""
    timestamp = headers.get("webhook-timestamp") or ""
    signature = headers.get("webhook-signature") or ""

    if not (event_id and timestamp and signature):
        raise WebhookError("missing webhook headers")

    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        raise WebhookError("bad webhook-timestamp")

    drift = abs((now if now is not None else time.time()) - sent_at)
    if drift > TOLERANCE_SECONDS:
        raise WebhookError("webhook timestamp outside tolerance")

    signed = b"%s.%s." % (event_id.encode("utf-8"), timestamp.encode("utf-8"))
    signed += body if isinstance(body, bytes) else body.encode("utf-8")

    expected = base64.b64encode(
        hmac.new(_key(secret), signed, hashlib.sha256).digest()
    ).decode("ascii")

    for candidate in _signatures(signature):
        if hmac.compare_digest(candidate, expected):
            return event_id

    raise WebhookError("no matching signature")