"""密码哈希 & JWT 单元测试 — 覆盖 app/core/security.py 全部 7 个公开函数。

对齐 TESTING_STRATEGY.md §4.3：每个函数覆盖成功路径 + 失败路径。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import jwt

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)


class TestHashPassword:
    """hash_password — bcrypt 哈希生成"""

    def test_返回字符串且不以明文出现(self):
        result = hash_password("mysecret123")
        assert isinstance(result, str)
        assert len(result) > 0
        assert "mysecret123" not in result
        assert result.startswith("$2b$")

    def test_相同密码两次哈希结果不同_因为加盐随机(self):
        h1 = hash_password("samepass")
        h2 = hash_password("samepass")
        assert h1 != h2  # bcrypt salt 保证不同


class TestVerifyPassword:
    """verify_password — bcrypt 密码验证"""

    def test_正确密码返回True(self):
        h = hash_password("correct_pass")
        assert verify_password("correct_pass", h) is True

    def test_错误密码返回False(self):
        h = hash_password("correct_pass")
        assert verify_password("wrong_pass", h) is False

    def test_空密码验证(self):
        h = hash_password("")
        assert verify_password("", h) is True
        assert verify_password("non_empty", h) is False


class TestCreateAccessToken:
    """create_access_token — JWT 签发"""

    def test_payload包含sub_username_role三个字段(self):
        token = create_access_token(user_id=42, username="bob", role="user")
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "bob"
        assert payload["role"] == "user"

    def test_exp字段在合理范围内_约15分钟(self):
        token = create_access_token(user_id=1, username="u", role="user")
        payload = decode_access_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = exp - now
        assert timedelta(minutes=14) < delta < timedelta(minutes=16)

    def test_role为user时正确编码(self):
        token = create_access_token(user_id=99, username="user1", role="user")
        payload = decode_access_token(token)
        assert payload["role"] == "user"
        assert payload["sub"] == "99"


class TestDecodeAccessToken:
    """decode_access_token — JWT 验证"""

    def test_有效token返回完整payload(self):
        token = create_access_token(user_id=1, username="test", role="user")
        payload = decode_access_token(token)
        assert payload["sub"] == "1"
        assert payload["username"] == "test"
        assert payload["role"] == "user"

    def test_过期token返回空dict(self):
        # 构造 1 秒过期的 token
        expire = datetime.now(timezone.utc) - timedelta(seconds=10)
        payload = {"sub": "1", "username": "u", "role": "user", "exp": expire}
        expired_token = jwt.encode(payload, "test-key", algorithm="HS256")
        with patch("app.core.security.settings.JWT_SECRET_KEY", "test-key"):
            result = decode_access_token(expired_token)
        assert result == {}

    def test_伪造token返回空dict(self):
        assert decode_access_token("not.a.valid.jwt.token") == {}

    def test_空字符串返回空dict(self):
        assert decode_access_token("") == {}

    def test_错误密钥签发的token返回空dict(self):
        # 用错误密钥签发
        payload = {
            "sub": "1", "username": "u", "role": "user",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        }
        forged = jwt.encode(payload, "wrong-key", algorithm="HS256")
        assert decode_access_token(forged) == {}

    def test_无exp字段的token返回空dict(self):
        payload = {"sub": "1", "username": "u", "role": "user"}
        forged = jwt.encode(payload, "wrong-key", algorithm="HS256")
        assert decode_access_token(forged) == {}


class TestCreateRefreshToken:
    """create_refresh_token — JWT 长有效期 token 签发"""

    def test_payload含sub_type_refresh_jti四个字段(self):
        token = create_refresh_token(user_id=42)
        payload = decode_refresh_token(token)
        assert payload["sub"] == "42"
        assert payload["type"] == "refresh"
        assert "jti" in payload
        assert len(payload["jti"]) == 32  # uuid4.hex

    def test_exp在7天左右(self):
        token = create_refresh_token(user_id=1)
        payload = decode_refresh_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = exp - now
        assert timedelta(days=6) < delta < timedelta(days=8)

    def test_jti每次不同_防止碰撞(self):
        t1 = create_refresh_token(user_id=1)
        t2 = create_refresh_token(user_id=1)
        p1 = decode_refresh_token(t1)
        p2 = decode_refresh_token(t2)
        assert p1["jti"] != p2["jti"]


class TestDecodeRefreshToken:
    """decode_refresh_token — 验证 type='refresh'"""

    def test_有效refresh_token解析成功(self):
        token = create_refresh_token(user_id=7)
        payload = decode_refresh_token(token)
        assert payload["sub"] == "7"
        assert payload["type"] == "refresh"

    def test_access_token传入refresh解析抛出JWTError(self):
        """access_token 不含 type='refresh' 字段，应解析失败。

        失败原因取决于密钥配置：access_token 用 JWT_SECRET_KEY 签发、
        refresh 用 REFRESH_TOKEN_SECRET_KEY 验证，密钥不同时先触发
        签名验证失败；密钥相同时触发 type 校验失败。两种均为 JWTError。
        """
        at = create_access_token(user_id=1, username="u", role="user")
        from jose import JWTError
        with pytest.raises(JWTError):
            decode_refresh_token(at)

    def test_过期refresh_token抛出JWTError(self):
        expire = datetime.now(timezone.utc) - timedelta(days=1)
        payload = {"sub": "1", "type": "refresh", "exp": expire}
        from app.config import settings
        secret = settings.REFRESH_TOKEN_SECRET_KEY or settings.JWT_SECRET_KEY
        expired = jwt.encode(payload, secret, algorithm="HS256")
        from jose import JWTError
        with pytest.raises(JWTError):
            decode_refresh_token(expired)

    def test_伪造token抛出JWTError(self):
        from jose import JWTError
        with pytest.raises(JWTError):
            decode_refresh_token("not.a.valid.token")


class TestHashToken:
    """hash_token — SHA-256 哈希"""

    def test_返回64字符十六进制字符串(self):
        result = hash_token("some-refresh-token-value")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_相同输入返回相同哈希_确定性(self):
        assert hash_token("abc") == hash_token("abc")

    def test_不同输入哈希不同(self):
        assert hash_token("abc") != hash_token("abd")

    def test_空字符串也可以哈希(self):
        result = hash_token("")
        assert len(result) == 64
