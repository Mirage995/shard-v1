```markdown
# rsa encryption python from scratch — SHARD Cheat Sheet

## Key Concepts
*   **RSA (Rivest–Shamir–Adleman):** A public-key cryptosystem widely used for secure data transmission.
*   **Prime Numbers:** Essential for generating the public and private keys in RSA.
*   **Modular Arithmetic:** Performing arithmetic operations within a specific modulus.
*   **Extended Euclidean Algorithm:** Used to find the modular inverse, crucial for key generation.
*   **Modular Exponentiation:** Efficiently computes large exponents modulo a number, used in encryption and decryption.
*   **Timing Attack:** A side-channel attack that exploits the time it takes to perform cryptographic operations.
*   **Side-Channel Attack:** Attacks based on information gained from the physical implementation of a cryptosystem.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Relatively easy to understand and implement the basic algorithm. | Vulnerable to various attacks if not implemented carefully (e.g., timing attacks). |
| Widely used and supported. | Key generation can be computationally intensive for large key sizes. |
| Provides both encryption and digital signature capabilities. | Requires large prime numbers for strong security. |

## Practical Example
```python
import random

def is_prime(n, k=5):
    if n <= 1: return False
    if n <= 3: return True
    s = 0
    r = n - 1
    while r % 2 == 0:
        s += 1
        r //= 2
    for _ in range(k):
        a = random.randrange(2, n - 1)
        x = pow(a, r, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True

def gcd(a, b):
    while b:
        a, b = b, a % b
    return a

def extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    d, x1, y1 = extended_gcd(b % a, a)
    x = y1 - (b // a) * x1
    y = x1
    return d, x, y

def generate_keypair(p, q):
    if not (is_prime(p) and is_prime(q)):
        raise ValueError('Both numbers must be prime.')
    elif p == q:
        raise ValueError('p and q cannot be equal')
    n = p * q
    phi = (p-1) * (q-1)
    e = random.randrange(1, phi)
    g = gcd(e, phi)
    while g != 1:
        e = random.randrange(1, phi)
        g = gcd(e, phi)
    d, x, y = extended_gcd(e, phi)
    d = x % phi
    if d < 0:
        d += phi
    return ((e, n), (d, n))

def encrypt(pk, plaintext):
    key, n = pk
    cipher = [pow(ord(char), key, n) for char in plaintext]
    return cipher

def decrypt(pk, ciphertext):
    key, n = pk
    plain = [chr(pow(char, key, n)) for char in ciphertext]
    return ''.join(plain)

if __name__ == '__main__':
    p = 61
    q = 53
    public, private = generate_keypair(p, q)
    print("Public key:", public)
    print("Private key:", private)
    message = "Hello RSA!"
    encrypted_msg = encrypt(public, message)
    print("Encrypted message:", encrypted_msg)
    decrypted_msg = decrypt(private, encrypted_msg)
    print("Decrypted message:", decrypted_msg)
```

## SHARD's Take
RSA provides a foundation for understanding public-key cryptography. However, a basic implementation is highly susceptible to attacks. Secure RSA implementations require careful attention to detail, including padding schemes and countermeasures against side-channel attacks.

```