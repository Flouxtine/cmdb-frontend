"""凭据加解密（Fernet，密钥文件 0600）"""
from cryptography.fernet import Fernet

from . import config


def _get_key():
    if config.SECRET_FILE.exists():
        return config.SECRET_FILE.read_bytes()
    key = Fernet.generate_key()
    config.SECRET_FILE.write_bytes(key)
    config.SECRET_FILE.chmod(0o600)
    return key


_fernet = Fernet(_get_key())


def encrypt(plain):
    return _fernet.encrypt(plain.encode()).decode() if plain else ""


def decrypt(cipher):
    if not cipher:
        return ""
    try:
        return _fernet.decrypt(cipher.encode()).decode()
    except Exception:
        return ""
