"""
Simple symmetric encryption/decryption with message authentication and timeout
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import Hash, SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class DecryptionError(Exception):
    pass


class Cipher:
    def __init__(self, password, salt, b64=False, iterations=480000):
        self._base64 = b64
        if not isinstance(salt, bytes) or len(salt) != 16:
            hash = Hash(SHA256())
            hash.update(salt if isinstance(salt, bytes) else str(salt).encode('utf8'))
            salt = hash.finalize()[:16]
        kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=iterations)
        self._cipher = Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode('utf8'))))

    def encrypt(self, data):
        token = self._cipher.encrypt(data)
        return token if self._base64 else base64.urlsafe_b64decode(token)

    def decrypt(self, data, ttl=None):
        token = data if self._base64 else base64.urlsafe_b64encode(data)
        try:
            return self._cipher.decrypt(token, ttl=ttl)
        except InvalidToken as exc:
            raise DecryptionError from exc
