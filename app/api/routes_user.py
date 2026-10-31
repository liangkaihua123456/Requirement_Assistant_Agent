"""用户鉴权路由：注册 / 登录 / 刷新 / 忘记密码 / 重置 / 当前用户。

方法约定：
- POST 用于会产生副作用或携带凭证的动作（register/login/refresh/forgot/reset/change/logout）
- GET  用于只读取当前用户信息（/me）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_reset_token,
    hash_password,
    verify_password,
)
from app.schemas.user import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.storage import repo_user

router = APIRouter(prefix="/user", tags=["user"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest):
    if await repo_user.get_by_username(req.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if req.email and await repo_user.get_by_email(req.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    user = await repo_user.create_user(
        username=req.username,
        password_hash=hash_password(req.password),
        email=req.email,
    )
    return UserOut(id=user["id"], username=user["username"], email=user["email"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = await repo_user.get_by_username(req.username) or await repo_user.get_by_email(req.username)
    # 统一错误信息，避免用户名枚举
    if user is None or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    return TokenResponse(
        access_token=create_access_token(user["id"]),
        refresh_token=create_refresh_token(user["id"]),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest):
    try:
        payload = decode_token(req.refresh_token, expected_type="refresh")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = await repo_user.get_by_id(int(payload["sub"]))
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return TokenResponse(
        access_token=create_access_token(user["id"]),
        refresh_token=create_refresh_token(user["id"]),
    )


@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    """按用户名或邮箱生成一次性重置 token。

    开发环境直接返回 token 便于联调；生产环境只回统一提示（真实邮件发送可在此接入 SMTP）。
    """
    user = await repo_user.get_by_username(req.account) or await repo_user.get_by_email(req.account)

    generic = {"message": "If the account exists, a reset link has been sent."}
    if user is None:
        return generic

    raw, token_hash = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    await repo_user.save_reset_token(user["id"], token_hash, expires_at)

    if get_settings().app_env.lower() == "development":
        return {"message": "Reset token created (development).", "reset_token": raw}
    return generic


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    result = await repo_user.consume_reset_token(req.token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    await repo_user.update_password(result["user_id"], hash_password(req.new_password))
    return {"message": "Password reset successfully"}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    user = await repo_user.get_by_id(current_user["id"])
    if user is None or not verify_password(req.old_password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Old password is incorrect")
    await repo_user.update_password(user["id"], hash_password(req.new_password))
    return {"message": "Password changed successfully"}


#个人信息
@router.get("/me", response_model=UserOut)
async def me(current_user: dict = Depends(get_current_user)):
    return UserOut(id=current_user["id"], username=current_user["username"], email=current_user["email"])


@router.post("/logout")
async def logout(_: dict = Depends(get_current_user)):
    """无状态 JWT：服务端不保存会话，前端清除本地 token 即可。

    如需强制失效，可在此把 jti 加入 Redis 黑名单。
    """
    return {"message": "Logout successful"}
