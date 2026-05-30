"""
鉴权相关的底层工具:
- 密码哈希 / 校验 (argon2)
- JWT 签发 / 解析

设计要点喵:
- 把"算法 + 参数 + 密钥"全部封进本模块,业务层(crud/api)只看到
  hash_password / verify_password / create_access_token / decode_access_token
  四个动词,以后想从 argon2 换 bcrypt、从 HS256 换 RS256,改这一处就够。
- argon2 是 OWASP 现行推荐:抗 GPU、抗 ASIC,自带 salt 与算法版本号,
  整串(算法/参数/salt/hash)塞进一个 VARCHAR 列就行,不用单独存 salt。
- JWT 不存 password_hash / 任何敏感字段,只放 sub(user_id) + exp + iat,
  权限/状态从 DB 现拉,token 泄漏的影响面被严格收住。
- 时间统一用 UTC + 时间戳整数,不踩"本地时区漂移"的坑。
- 自定义异常 InvalidTokenError 让上层 deps 能精确区分"过期/伪造/格式错"
  与"业务异常",转成 401 而不是 500。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.core.config import settings


# 学习要点：PasswordHasher() 用默认参数即可——argon2-cffi 的默认值
# 已经对齐 OWASP 推荐 (memory=65536KB, time=3, parallelism=4)。
# 全局单例:PasswordHasher 内部无状态,可以多线程/多协程并发复用,
# 不需要每次调用 hash 都新建,避免开销。
_hasher = PasswordHasher()


# ============================================================
# 密码哈希
# ============================================================
def hash_password(plain: str) -> str:
    """
    用 argon2 生成密码哈希。
    返回值形如:
      $argon2id$v=19$m=65536,t=3,p=4$<salt-b64>$<hash-b64>
    长度 ~96 字符,直接塞进 users.password_hash (VARCHAR(255))。
    """
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    """
    校验明文密码与数据库里的哈希是否匹配。
    - 匹配: True
    - 不匹配 / 哈希格式损坏: False (统一返回 False,不向上抛,
      避免登录接口因为"哈希格式坏掉"返回 500 暴露内部状态)
    学习要点喵:argon2 的 verify 失败有 3 种异常,都视为"鉴权失败"。
    """
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ============================================================
# JWT
# ============================================================
class InvalidTokenError(Exception):
    """JWT 解析失败的统一异常,deps 层捕获后转 401。"""


def create_access_token(
    *,
    subject: str,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    签发一个 access token。
    必填: subject(放进 sub 字段,一般是 user_id)
    可选: expires_minutes 覆盖默认有效期; extra_claims 追加自定义字段
          (如 username,但敏感数据 / 经常变动的字段不要塞 JWT)。

    学习要点喵:JWT 三大标准时间字段:
      - iat (issued at)  签发时间
      - exp (expires at) 过期时间
      - nbf (not before) 生效时间(本项目暂不需要)
    用 UTC + 整数秒,跨时区/跨服务永远不会因为"本地时间不一样"对不上。
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.JWT_EXPIRE_MINUTES
    )

    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        # 学习要点喵:把 extra_claims 放在前面、标准字段放在后面再 update
        # 不行——会让用户传的 sub/exp 覆盖掉我们刚算的。所以反过来:
        # 先 extra,再用真值覆盖,确保标准字段权威。
        merged = {**extra_claims, **payload}
        payload = merged

    token = jwt.encode(
        payload,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    return token


def decode_access_token(token: str) -> dict[str, Any]:
    """
    解析并校验 JWT。
    - 签名错 / 过期 / 格式错 → 抛 InvalidTokenError
    - 通过 → 返回 payload dict
    学习要点喵:PyJWT 默认就会校验 exp,过期会抛 ExpiredSignatureError。
    我们把它统一翻译成自定义异常,让上层只 except 一个类型就够。
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as e:
        raise InvalidTokenError("token 已过期") from e
    except jwt.InvalidTokenError as e:
        # PyJWT 所有解析/签名/格式错误的基类
        raise InvalidTokenError("token 无效") from e

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        # 防御:就算签名通过,sub 字段被篡改/缺失也算无效
        raise InvalidTokenError("token 缺少 sub 字段")
    return payload
