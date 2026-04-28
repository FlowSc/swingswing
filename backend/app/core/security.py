from cryptography.fernet import Fernet

from app.core.config import get_settings


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def _fernet() -> Fernet:
    return Fernet(get_settings().broker_encryption_key.encode("utf-8"))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
