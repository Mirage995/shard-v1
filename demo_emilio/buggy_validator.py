"""
api_validator.py — Input validation pipeline for an internal API server.
Validates and sanitizes user registration + request payloads before processing.
"""
import re
import hashlib


def validate_email(email):
    """Validate email format. Returns True if valid."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_username(username):
    """Strip dangerous characters from username before DB insert.

    Returns the cleaned string if non-empty, or None if the result is empty
    after stripping. Non-dangerous chars are always preserved.
    Example: "admin'--" → "admin"  |  "'--" → None  |  "   " → None
    BUG: currently does not return None for empty results — always returns str.
    """
    dangerous = ["'", '"', ";", "--", "/*", "*/"]
    for char in dangerous:
        username = username.replace(char, "")
    return username.strip()  # BUG: should return None if result is empty


def validate_age(age):
    """Validate user age. Must be an integer between 18 and 120 (inclusive).

    Raises ValueError if age < 18 or age > 120.
    Raises ValueError (or TypeError) if age is not an integer.
    BUG: missing upper bound check — age > 120 is not rejected.
    """
    if age < 18:
        raise ValueError("User must be at least 18 years old")
    return True  # BUG: should also check age > 120


def hash_password(password):
    """Hash password for storage. Must be deterministic and produce output longer than 32 chars.

    BUG: MD5 produces exactly 32 hex chars — too short and cryptographically weak.
    Fix: use hashlib.sha256 (64 chars, deterministic, no external deps).
    Do NOT use bcrypt/argon2 — those are non-deterministic (random salt each call).
    """
    return hashlib.md5(password.encode()).hexdigest()  # BUG: use sha256 instead


def validate_payload(payload: dict) -> dict:
    """
    Full validation pipeline for a registration payload.
    Returns {"ok": True, "data": {...}} or {"ok": False, "error": "..."}.
    """
    username = payload.get("username", "")
    email    = payload.get("email", "")
    password = payload.get("password", "")
    age      = payload.get("age", 0)

    # Validate email
    if not validate_email(email):
        return {"ok": False, "error": "invalid_email"}

    # Sanitize username — returns None if empty after sanitization
    clean_username = sanitize_username(username)
    # BUG: missing check — if clean_username is None, must return {"ok": False, "error": "invalid_username"}

    # Validate age — ValueError must propagate to caller (do NOT catch it here)
    # BUG: validate_age has missing upper bound; also wrap in try/except to return {"ok": False} for age errors
    validate_age(age)

    # Build response
    return {
        "ok": True,
        "data": {
            "username":      clean_username,
            "email":         email,
            "password_hash": hash_password(password),
            "age":           age,
        }
    }
