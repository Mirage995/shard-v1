# fail fast principle applied to python applied to post-quantum security margin — SHARD Cheat Sheet

## Key Concepts

- **Fail Fast Principle**: Design philosophy where systems detect and report errors immediately rather than allowing silent failures to propagate
- **Post-Quantum Security Margin**: Extra cryptographic strength beyond minimum requirements to protect against future quantum computing advances
- **Early Validation**: Verify cryptographic parameters, key sizes, and algorithm choices at initialization time, not during runtime
- **Parameter Bounds Checking**: Enforce minimum security levels (e.g., NIST security levels 1-5) before any cryptographic operations
- **Quantum-Resistant Algorithms**: Lattice-based (CRYSTALS-Kyber), hash-based (SPHINCS+), and code-based cryptography that resist quantum attacks
- **Security Level Assertions**: Explicit checks that cryptographic primitives meet post-quantum security thresholds (typically ≥128-bit quantum security)
- **Defensive Programming**: Use Python's type hints, assertions, and exceptions to catch security misconfigurations early
- **Circuit Validation**: For quantum implementations, verify circuit depth and gate counts don't compromise security margins

## Pro & Contra

| Pro | Contro |
|-----|--------|
| Prevents deployment of weak cryptographic configurations that could be broken by quantum computers | Additional validation overhead may slow initialization time |
| Catches parameter errors (undersized keys, weak algorithms) before data is encrypted | Requires developers to understand post-quantum security levels and margins |
| Makes security assumptions explicit and testable in code | May reject configurations that are "good enough" for current threats but fail future-proofing |
| Reduces attack surface by eliminating silent degradation to weaker algorithms | Strict validation can break backward compatibility with legacy systems |
| Facilitates security audits through clear assertion points | Over-aggressive checks might cause false positives during testing |
| Forces conscious decisions about security/performance tradeoffs | Requires ongoing updates as quantum computing capabilities evolve |

## Practical Example

```python
from typing import Literal
import sys

# Post-quantum security levels (NIST standards)
SecurityLevel = Literal[1, 2, 3, 4, 5]

class PostQuantumConfig:
    """Fail-fast configuration for post-quantum cryptography"""
    
    # Minimum acceptable security margins (bits of quantum security)
    MIN_QUANTUM_SECURITY = 128
    RECOMMENDED_QUANTUM_SECURITY = 192
    
    def __init__(self, algorithm: str, key_size: int, security_level: SecurityLevel):
        self.algorithm = algorithm
        self.key_size = key_size
        self.security_level = security_level
        
        # FAIL FAST: Validate immediately
        self._validate_algorithm()
        self._validate_key_size()
        self._validate_security_margin()
    
    def _validate_algorithm(self):
        """Ensure only post-quantum resistant algorithms are used"""
        approved_algorithms = {
            'CRYSTALS-Kyber', 'CRYSTALS-Dilithium', 
            'SPHINCS+', 'FALCON', 'NTRU'
        }
        if self.algorithm not in approved_algorithms:
            raise ValueError(
                f"FAIL FAST: Algorithm '{self.algorithm}' is not post-quantum secure. "
                f"Use one of: {approved_algorithms}"
            )
    
    def _validate_key_size(self):
        """Verify key sizes meet minimum post-quantum requirements"""
        min_key_sizes = {
            'CRYSTALS-Kyber': 768,    # Kyber-768 minimum
            'CRYSTALS-Dilithium': 2420,
            'SPHINCS+': 256,
            'FALCON': 512,
            'NTRU': 509
        }
        
        required = min_key_sizes.get(self.algorithm, 0)
        if self.key_size < required:
            raise ValueError(
                f"FAIL FAST: Key size {self.key_size} too small for {self.algorithm}. "
                f"Minimum required: {required} bits for post-quantum security margin."
            )
    
    def _validate_security_margin(self):
        """Ensure adequate security margin against quantum attacks"""
        # Map NIST security levels to quantum security bits
        quantum_security_bits = {
            1: 128,  # AES-128 equivalent
            2: 192,  # AES-192 equivalent
            3: 256,  # AES-256 equivalent
            4: 256,  # Higher than AES-256
            5: 256   # Highest security
        }
        
        actual_security = quantum_security_bits[self.security_level]
        
        if actual_security < self.MIN_QUANTUM_SECURITY:
            raise SecurityError(
                f"FAIL FAST: Security level {self.security_level} provides only "
                f"{actual_security} bits of quantum security. "
                f"Minimum required: {self.MIN_QUANTUM_SECURITY} bits."
            )
        
        if actual_security < self.RECOMMENDED_QUANTUM_SECURITY:
            import warnings
            warnings.warn(
                f"Security margin warning: {actual_security} bits < "
                f"recommended {self.RECOMMENDED_QUANTUM_SECURITY} bits. "
                f"Consider using security level 3+."
            )

class SecurityError(Exception):
    """Raised when security margins are insufficient"""
    pass

# Example usage
if __name__ == "__main__":
    try:
        # This will FAIL FAST - RSA is not post-quantum secure
        weak_config = PostQuantumConfig("RSA", 2048, 1)
    except ValueError as e:
        print(f"✗ Caught early: {e}\n")
    
    try:
        # This will FAIL FAST - key size too small
        weak_kyber = PostQuantumConfig("CRYSTALS-Kyber", 512, 1)
    except ValueError as e:
        print(f"✗ Caught early: {e}\n")
    
    try:
        # This succeeds but warns about security margin
        acceptable_config = PostQuantumConfig("CRYSTALS-Kyber", 768, 1)
        print(f"✓ Configuration accepted: {acceptable_config.algorithm}")
    except Exception as e:
        print(f"✗ Failed: {e}")
    
    # This succeeds with strong security margin
    strong_config = PostQuantumConfig("CRYSTALS-Kyber", 1024, 3)
    print(f"✓ Strong configuration: {strong_config.algorithm} "
          f"with security level {strong_config.security_level}")
```

## SHARD's Take

Applying fail-fast principles to post-quantum security margins is essential because cryptographic failures are catastrophic and often irreversible—once data is captured, future quantum computers could decrypt it retroactively. By validating security parameters at initialization rather than runtime, we create a defensive barrier that prevents "harvest now, decrypt later" vulnerabilities. The computational cost of upfront validation is negligible compared to the existential risk of deploying quantum-vulnerable cryptography in production systems.

---
*Generated by SHARD Autonomous Learning Engine*