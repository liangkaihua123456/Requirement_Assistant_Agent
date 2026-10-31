"""FastAPI 鉴权依赖。

支持两种取 token 方式：
- 标准 `Authorization: Bearer <token>`（普通 REST 请求）
- 查询参数 `?token=<token>`（EventSource / SSE 无法设置 header，用于兜底）
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.storage import repo_user

_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    token: str | None = Query(None, description="SSE / EventSource token fallback"),
) -> dict:
    raw = credentials.credentials if credentials else token
    if not raw:
        raise _UNAUTHORIZED
    try:
        payload = decode_token(raw, expected_type="access")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.PyJWTError:
        raise _UNAUTHORIZED

    user = await repo_user.get_by_id(int(payload["sub"]))
    if user is None or not user["is_active"]:
        raise _UNAUTHORIZED
    return user
