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
    """Strip dangerous characters from username before DB insert."""
    dangerous = ["'", '"', ";", "--", "/*", "*/"]
    for char in dangerous:
        username = username.replace(char, "")
    return username.strip()


def validate_age(age):
    """Validate user age. Must be between 18 and 120."""
    if age < 18:
        raise ValueError("User must be at least 18 years old")
    return True


def hash_password(password):
    """Hash password for storage."""
    return hashlib.md5(password.encode()).hexdigest()


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

    # Sanitize username
    clean_username = sanitize_username(username)

    # Validate age
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
