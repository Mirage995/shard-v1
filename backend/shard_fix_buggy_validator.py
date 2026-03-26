"""
api_validator.py — Input validation pipeline for an internal API server.
Validates and sanitizes user registration + request payloads before processing.
"""
import re
import hashlib


def validate_email(email):
    """Validate email format. Returns True if valid."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not isinstance(email, str):
        return False
    try:
        email.encode('utf-8').decode('ascii')
    except UnicodeDecodeError:
        return False
    return bool(re.match(pattern, email))


def sanitize_username(username):
    """Strip dangerous characters from username before DB insert."""
    if not isinstance(username, str):
        return None
    username = re.sub(r'[^a-zA-Z0-9_]+', '', username)
    username = username.strip()
    if len(username) > 32:
        return None
    if not username:
        return None
    return username


def validate_age(age):
    """Validate user age. Must be between 18 and 120."""
    if age is None:
        raise ValueError("Age cannot be None")
    if isinstance(age, str):
        try:
            age = int(age)
        except ValueError:
            raise ValueError("Age must be an integer")
    if not isinstance(age, int):
        raise ValueError("Age must be an integer")
    if age < 18:
        raise ValueError("User must be at least 18 years old")
    if age > 120:
        raise ValueError("User must be 120 years old or younger")
    return True


def hash_password(password):
    """Hash password for storage."""
    if password is None:
        raise ValueError("Password cannot be None")
    if not password:
        raise ValueError("Password cannot be empty")
    return hashlib.sha256(password.encode()).hexdigest()


def validate_payload(payload: dict) -> dict:
    """
    Full validation pipeline for a registration payload.
    Returns {"ok": True, "data": {...}} or {"ok": False, "error": "..."}.
    """
    if payload is None:
        return {"ok": False, "error": "invalid_payload"}

    username = payload.get("username")
    email = payload.get("email")
    password = payload.get("password")
    age = payload.get("age")

    if username is None or email is None or password is None or age is None:
        return {"ok": False, "error": "missing_field"}

    # Validate email
    if not validate_email(email):
        return {"ok": False, "error": "invalid_email"}

    # Sanitize username
    clean_username = sanitize_username(username)
    if clean_username is None:
        return {"ok": False, "error": "invalid_username"}

    # Validate age
    try:
        age = int(age)
        validate_age(age)
    except ValueError as e:
        return {"ok": False, "error": f"invalid_age: {e}"}
    except TypeError:
        return {"ok": False, "error": "invalid_age_type"}

    if not isinstance(password, str) or len(password) < 8:
        return {"ok": False, "error": "invalid_password"}

    # Build response
    return {
        "ok": True,
        "data": {
            "username": clean_username,
            "email": email,
            "password_hash": hash_password(password),
            "age": age,
        }
    }