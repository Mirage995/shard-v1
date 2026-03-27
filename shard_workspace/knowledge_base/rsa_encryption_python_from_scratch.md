```markdown
# rsa encryption python from scratch — SHARD Cheat Sheet

## Key Concepts
*   **RSA (Rivest–Shamir–Adleman):** A public-key cryptosystem widely used for secure data transmission.
*   **Prime Numbers:** Essential for generating the public and private keys in RSA.
*   **Modular Arithmetic:** Performing arithmetic operations within a specific modulus.
*   **Public Key:** Used for encryption; can be shared openly.
*   **Private Key:** Used for decryption; must be kept secret.
*   **Encryption:** Converting plaintext to ciphertext using the public key.
*   **Decryption:** Converting ciphertext to plaintext using the private key.
*   **Key Generation:** The process of creating the public and private key pair.
*   **Modular Exponentiation:** Efficiently computing large exponents modulo a number.
*   **Extended Euclidean Algorithm:** Used to find the modular multiplicative inverse.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Educational: Deep understanding of RSA. | Security: Vulnerable to attacks if not implemented correctly. |
| Customizable: Full control over the implementation. | Complexity: Requires knowledge of number theory. |
| No dependencies: Doesn't rely on external libraries. | Performance: Slower than optimized libraries. |

## Practical Example
```python
import random

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

def modular_inverse(a, m):
    g, x, y = extended_gcd(a, m)
    if g != 1:
        raise Exception('Modular inverse does not exist')
    else:
        return x % m

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

    d = modular_inverse(e, phi)

    return ((e, n), (d, n))

def is_prime(num):
    if num < 2:
        return False
    for i in range(2, int(num**0.5) + 1):
        if num % i == 0:
            return False
    return True

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
Implementing RSA from scratch provides a solid understanding of the underlying mathematical principles. However, creating a secure RSA implementation requires careful attention to detail, especially in prime number generation and protection against side-channel attacks. For production systems, using well-vetted cryptographic libraries is strongly recommended.