"""
Shared helper for API tests that need an authenticated session (8A.1/8A.2).

Signup already signs the user in (the Flask session cookie is set on the
returned test client), and since 8A.2 state-changing calls also require the
session-bound CSRF token, the returned client transparently injects the
X-CSRF-Token header into every request. Emails are unique per call so
repeated runs never hit the duplicate-email rejection.
"""

from uuid import uuid4

DEFAULT_TEST_PASSWORD = "Passw0rd123"


def _csrf_wrapped(client):
    """Inject the session CSRF token into every request the client makes."""
    data = client.get("/api/auth/me").get_json()
    token = (data or {}).get("csrf_token")
    if not token:
        return client
    original_open = client.open

    def open_with_csrf(*args, **kwargs):
        headers = kwargs.pop("headers", None) or {}
        headers.setdefault("X-CSRF-Token", token)
        kwargs["headers"] = headers
        return original_open(*args, **kwargs)

    client.open = open_with_csrf
    return client


def signup_and_login(app_module, email=None, name="Test User",
                     password=DEFAULT_TEST_PASSWORD):
    """Create a fresh user on app_module's test client and return (client, email).

    The client is CSRF-aware: POST/DELETE calls succeed without each test
    having to manage tokens itself.
    """
    email = email or f"{uuid4().hex}@test.example"
    client = app_module.app.test_client()
    resp = client.post(
        "/api/auth/signup",
        json={"name": name, "email": email, "password": password},
    )
    if resp.status_code != 201:
        raise RuntimeError(f"test signup failed: {resp.status_code} {resp.get_json()}")
    return _csrf_wrapped(client), email
