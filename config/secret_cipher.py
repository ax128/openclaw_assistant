"""
Gateway 敏感配置（token、password）的本地加密存储。
密钥存于 config/.gateway_key，加密后写入 gateway.json 时带前缀 enc:，读取时解密。
"""
import os
from utils.logger import logger

# 加密值前缀，用于区分明文（兼容旧配置）与密文
_ENCRYPTED_PREFIX = "enc:"


def _key_file_path(config_dir: str) -> str:
    """密钥文件路径：config_dir/.gateway_key"""
    return os.path.join(config_dir, ".gateway_key")


def _get_fernet(config_dir: str):
    """获取或创建密钥文件，返回 Fernet 实例。"""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("未安装 cryptography，敏感配置将明文存储。可执行: pip install cryptography")
        return None
    path = _key_file_path(config_dir)
    if os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                key = f.read().strip()
            return Fernet(key)
        except Exception as e:
            logger.warning(f"读取密钥文件失败，将明文处理: {e}")
            return None
    try:
        key = Fernet.generate_key()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(key)
        return Fernet(key)
    except Exception as e:
        logger.warning(f"创建密钥文件失败，将明文处理: {e}")
        return None


def encrypt_if_available(plain: str, config_dir: str) -> str:
    """
    若可用则加密后返回 enc: + base64；否则返回原文。
    空字符串直接返回空字符串。
    """
    if not plain or not isinstance(plain, str):
        return plain or ""
    f = _get_fernet(config_dir)
    if f is None:
        return plain
    try:
        token = f.encrypt(plain.encode("utf-8"))
        return _ENCRYPTED_PREFIX + token.decode("ascii")
    except Exception as e:
        logger.debug(f"加密失败，保存明文: {e}")
        return plain


def decrypt_if_encrypted(value: str, config_dir: str) -> str:
    """
    若为 enc: 开头的密文则解密后返回；否则返回原文。
    非字符串或空直接返回原值。
    """
    if not value or not isinstance(value, str):
        return value or ""
    if not value.startswith(_ENCRYPTED_PREFIX):
        return value
    f = _get_fernet(config_dir)
    if f is None:
        return value
    try:
        token = value[len(_ENCRYPTED_PREFIX) :].encode("ascii")
        return f.decrypt(token).decode("utf-8")
    except Exception as e:
        logger.debug(f"解密失败，返回原值: {e}")
        return value
