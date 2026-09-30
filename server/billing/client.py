import os
import requests

PROD_BASE = "https://api.polar.sh/v1"
SANDBOX_BASE = "https://sandbox-api.polar.sh/v1"
TIMEOUT = 15

class BillingError(Exception):
    """Something the buyer should see as a polite failure, not a 500."""


def base_url():
    sandbox = (os.environ.get("POLAR_SANDBOX") or "").lower() in ("1", "true", "yes")
    return SANDBOX_BASE if sandbox else PROD_BASE


def _token():
    token = (os.environ.get("POLAR_ACCESS_TOKEN") or "").strip()
    if not token:
        raise BillingError("Payments are not switched on yet.")
    return token

def _post(path, payload):
    try:
        resp = requests.post(
            base_url() + path,
            headers={"Authorization": "Bearer " + _token(),
                     "Content-Type": "application/json"},
            json=payload, timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise BillingError("Could not reach the payment provider.") from exc

    if resp.status_code >= 400:
        raise BillingError("The payment provider rejected that request. "
                           "(%s: %s)" % (resp.status_code, resp.text[:300]))

def create_checkout(product_id, user, success_url, metadata=None):
    body = {
        "products": [product_id],
        "success_url": success_url,
        "external_customer_id": str(user.id),
        "metadata": dict(metadata or {}, user_id=str(user.id)),
    }
    if user.email:
        body["customer_email"] = user.email

    data = _post("/checkouts/", body)
    url = data.get("url")
    if not url:
        raise BillingError("The payment provider did not return a checkout URL.")
    return url

def create_portal_session(user, return_url= None):
    body = {"external_customer_id": str(user.id)}
    if return_url:
        body["return_url"] = return_url

    data = _post("/customer-sessions/", body)
    url = data.get("customer_portal_url")
    if not url:
        raise BillingError("The payment provider did not return a portal URL.")
    return url
