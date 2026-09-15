"""PIN hashing. PINs are never stored in clear text.

Stored format: pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
Keeping the iteration count in the value lets the work factor evolve without
breaking existing accounts.
"""

from __future__ import annotations

import hashlib
import hmac
import random
import secrets

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000  # OWASP recommendation for PBKDF2-HMAC-SHA256


def generate_pin(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    return f"{rng.randrange(10_000):04d}"


def hash_pin(pin: str, iterations: int = DEFAULT_ITERATIONS, salt: bytes | None = None) -> str:
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$")
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(candidate.hex(), digest_hex)
