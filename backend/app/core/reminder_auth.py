"""Scoped bearer tokens for reminder/feedback APIs; issue using local admin CLI."""
import hashlib
import hmac
import time
from uuid import UUID
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.db.session import get_db
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings

bearer = HTTPBearer(auto_error=False)


def issue_token(student_id: UUID, lifetime=86400):
    if len(settings.reminder_api_secret) < 32:
        raise ValueError('REMINDER_API_SECRET至少32字符')
    data = f'{student_id}.{int(time.time())+lifetime}'
    sig = hmac.new(settings.reminder_api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f'{data}.{sig}'


def authenticated_student(request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session=Depends(get_db)) -> UUID:
    if credentials is None:
        from app.core.auth import require_student
        return require_student(request,db).id
    if len(settings.reminder_api_secret) < 32:
        raise HTTPException(503, '提醒接口鉴权密钥尚未配置')
    try:
        if credentials is None:
            raise ValueError()
        student, expiry, sig = credentials.credentials.split('.')
        data = f'{student}.{expiry}'
        expected = hmac.new(settings.reminder_api_secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or int(expiry) <= time.time():
            raise ValueError()
        return UUID(student)
    except (ValueError, TypeError):
        raise HTTPException(401, '无效或过期的学生访问令牌')
