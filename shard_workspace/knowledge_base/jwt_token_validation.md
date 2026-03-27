# jwt token validation — SHARD Cheat Sheet

## Key Concepts
*   **JWT (JSON Web Token):** A compact, URL-safe means of representing claims to be transferred between two parties.
*   **Signature Verification:** Ensuring the JWT hasn't been tampered with using the secret key or public key.
*   **Claims Validation:** Verifying standard claims (exp, iat, iss, aud, sub) and custom claims.
*   **Expiration (exp):** Checking if the token is still valid based on its expiration time.
*   **Issuer (iss):** Validating the token was issued by an expected authority.
*   **Audience (aud):** Confirming the token is intended for the current application.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Enhances security by verifying token authenticity. | Can add complexity to the authentication process. |
| Prevents unauthorized access to resources. | Requires secure storage and management of signing keys. |
| Allows for stateless authentication. | Vulnerable if signing key is compromised. |

## Practical Example
```python
import jwt
import time

# Example secret key (keep this secure in a real application)
SECRET_KEY = "your-secret-key"

# Sample JWT payload
payload = {
    "sub": "user123",
    "name": "John Doe",
    "iat": time.time(),
    "exp": time.time() + 3600,  # Expires in 1 hour
    "iss": "your-app",
    "aud": "your-app-users"
}

# Encode the JWT
encoded_jwt = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
print(f"Encoded JWT: {encoded_jwt}")

# Decode and validate the JWT
try:
    decoded_payload = jwt.decode(encoded_jwt, SECRET_KEY, algorithms=["HS256"], audience="your-app-users", issuer="your-app")
    print(f"Decoded Payload: {decoded_payload}")
except jwt.ExpiredSignatureError:
    print("Token has expired")
except jwt.InvalidAudienceError:
    print("Invalid audience")
except jwt.InvalidIssuerError:
    print("Invalid issuer")
except jwt.InvalidSignatureError:
    print("Invalid signature")
except Exception as e:
    print(f"Token is invalid: {e}")
```

## SHARD's Take
JWT validation is essential for securing APIs and applications by ensuring that only authorized users can access protected resources. Proper validation includes verifying the signature, expiration, issuer, and audience claims to prevent token manipulation and replay attacks. Neglecting any of these steps can lead to significant security vulnerabilities.