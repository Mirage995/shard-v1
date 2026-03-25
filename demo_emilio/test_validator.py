"""
test_validator.py — CI/CD pre-deploy test suite for api_validator.
These tests must ALL pass before a deploy is allowed.
"""
import pytest
from fixed_buggy_validator import validate_email, sanitize_username, validate_age, hash_password, validate_payload


# ── validate_email ────────────────────────────────────────────────────────────

def test_email_valid_basic():
    assert validate_email("user@example.com") is True

def test_email_valid_subdomains():
    assert validate_email("user@mail.example.co.uk") is True

def test_email_valid_plus_tag():
    # Gmail-style tags are valid RFC 5321 addresses
    assert validate_email("user+tag@example.com") is True

def test_email_invalid_no_at():
    assert validate_email("userexample.com") is False

def test_email_invalid_empty():
    assert validate_email("") is False


# ── sanitize_username ─────────────────────────────────────────────────────────

def test_sanitize_normal():
    assert sanitize_username("andrea95") == "andrea95"

def test_sanitize_removes_sql_injection():
    assert sanitize_username("admin'--") == "admin"

def test_sanitize_empty_after_strip():
    # After removing dangerous chars "'\";;--" the result is "" — sanitize_username
    # must detect this and return None. Callers check: if clean is None: reject.
    result = sanitize_username("'\";;--")
    assert result is None, "sanitize_username must return None when result is empty after stripping dangerous chars"

def test_sanitize_whitespace_only():
    # "   ".strip() == "" — sanitize_username must return None for whitespace-only input.
    result = sanitize_username("   ")
    assert result is None, "sanitize_username must return None for whitespace-only usernames"


# ── validate_age ──────────────────────────────────────────────────────────────

def test_age_valid():
    assert validate_age(25) is True

def test_age_boundary_18():
    assert validate_age(18) is True

def test_age_too_young():
    # Lower bound: age < 18 must raise ValueError
    with pytest.raises(ValueError):
        validate_age(16)

def test_age_string_input():
    # Should raise TypeError or ValueError, not crash with unhandled exception
    with pytest.raises((TypeError, ValueError)):
        validate_age("venticinque")

def test_age_over_120():
    # Upper bound: age > 120 must raise ValueError. validate_age must check BOTH bounds:
    # if age < 18: raise ValueError; if age > 120: raise ValueError
    with pytest.raises(ValueError):
        validate_age(150)


# ── hash_password ─────────────────────────────────────────────────────────────

def test_hash_is_deterministic():
    assert hash_password("secret") == hash_password("secret")

def test_hash_different_passwords_differ():
    assert hash_password("secret") != hash_password("other")

def test_hash_not_plaintext():
    assert hash_password("secret") != "secret"

def test_hash_not_md5_unsalted():
    # MD5 hexdigest is exactly 32 chars — use a stronger algorithm (e.g. SHA-256 = 64 chars).
    # IMPORTANT: hash_password must remain deterministic (same input → same output every time),
    # so do NOT use bcrypt/argon2 with a random salt. hashlib.sha256 is sufficient here.
    result = hash_password("password123")
    assert len(result) > 32, "Password hash looks like bare MD5 — must use a stronger algorithm"


# ── validate_payload ──────────────────────────────────────────────────────────

def test_payload_valid():
    payload = {"username": "andrea", "email": "andrea@example.com", "password": "strongpw1!", "age": 25}
    result = validate_payload(payload)
    assert result["ok"] is True

def test_payload_invalid_email():
    payload = {"username": "andrea", "email": "not-an-email", "password": "pw", "age": 25}
    result = validate_payload(payload)
    assert result["ok"] is False
    assert result["error"] == "invalid_email"

def test_payload_username_empty_after_sanitize():
    # sanitize_username("'--") returns None — validate_payload must detect None and return ok=False.
    # Check: if clean_username is None: return {"ok": False, "error": "invalid_username"}
    payload = {"username": "'--", "email": "a@b.com", "password": "pw", "age": 25}
    result = validate_payload(payload)
    assert result["ok"] is False, "None username after sanitization must be rejected"

def test_payload_age_too_young():
    # validate_payload must catch the ValueError from validate_age and return ok=False.
    # The error key must contain "age" (e.g. "age_too_young" or "User must be at least 18").
    payload = {"username": "andrea", "email": "a@b.com", "password": "pw", "age": 15}
    result = validate_payload(payload)
    assert result["ok"] is False
    assert "age" in result.get("error", "").lower(), "error message must mention 'age'"

def test_payload_missing_fields():
    # Empty payload should not crash — should return error gracefully
    result = validate_payload({})
    assert result["ok"] is False
