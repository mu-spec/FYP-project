"""
Shared helper for API tests that need an authenticated session (8A.1).

Signup already signs the user in (the Flask session cookie is set on the
returned test client), so a single call yields a ready-to-use client.
Emails are unique per call so repeated runs never hit the duplicate-email
rejection.
"""

from uuid import uuid4

DEFAULT_TEST_PASSWORD = "Passw0rd123"


def signup_and_login(app_module, email=None, name="Test User",
                     password=DEFAULT_TEST_PASSWORD):
    """Create a fresh user on app_module's test client and return (client, email)."""
    email = email or f"{uuid4().hex}@test.example"
    client = app_module.app.test_client()
    resp = client.post(
        "/api/auth/signup",
        json={"name": name, "email": email, "password": password},
    )
    if resp.status_code != 201:
        raise RuntimeError(f"test signup failed: {resp.status_code} {resp.get_json()}")
    return client, email
