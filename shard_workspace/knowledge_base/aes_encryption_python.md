# aes encryption python — SHARD Cheat Sheet

## Key Concepts
*   **AES (Advanced Encryption Standard):** A symmetric block cipher widely used for secure data encryption.
*   **PyCryptodome:** A Python library providing cryptographic primitives, including AES.
*   **Cipher Modes (CBC, CTR, GCM):** Different methods of applying AES to data blocks, each with varying security and performance characteristics.
*   **Key:** A secret value used to encrypt and decrypt data.
*   **IV (Initialization Vector):** A random value used to ensure unique ciphertexts, especially in CBC mode.
*   **Nonce:** A number used once to avoid replay attacks, especially in GCM mode.
*   **Padding:** Adding extra data to ensure the plaintext is a multiple of the block size.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Strong encryption algorithm | Requires careful key management |
| Widely supported and implemented | Can be vulnerable if used incorrectly (e.g., weak keys, improper IV handling) |
| Relatively fast and efficient | Requires understanding of different cipher modes and their implications |
| Available in many libraries | Can be complex to implement correctly without proper knowledge |

## Practical Example

```python
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad, unpad
import os

def encrypt_aes(data, key):
    iv = get_random_bytes(AES.block_size)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(data.encode('utf-8'), AES.block_size))
    return iv + ciphertext

def decrypt_aes(ciphertext, key):
    iv = ciphertext[:AES.block_size]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext[AES.block_size:]), AES.block_size)
    return plaintext.decode('utf-8')

# Example Usage
key = os.urandom(16)  # 128-bit key
plaintext = "This is a secret message."
ciphertext = encrypt_aes(plaintext, key)
decrypted_plaintext = decrypt_aes(ciphertext, key)

print(f"Plaintext: {plaintext}")
print(f"Ciphertext: {ciphertext.hex()}")
print(f"Decrypted Plaintext: {decrypted_plaintext}")
```

## SHARD's Take
AES encryption provides strong security when implemented correctly. Choosing the appropriate cipher mode (e.g., GCM for authenticated encryption) and managing keys securely are crucial. Always use a well-vetted cryptography library like PyCryptodome to avoid common pitfalls.