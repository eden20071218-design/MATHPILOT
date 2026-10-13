"""Opaque HttpOnly sessions. Never accept a caller-supplied student identity."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.auth import LoginSession
from app.models.entities import Student

COOKIE='mathpilot_session'


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def password_hash(password, salt=None):
    salt=salt or secrets.token_hex(16)
    result=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    return salt+':'+result


def verify_password(password, encoded):
    return hmac.compare_digest(password_hash(password,encoded.split(':')[0]),encoded)


def csrf(request: Request):
    if request.method in ('GET','HEAD','OPTIONS'):
        return
    if request.headers.get('X-MathPilot-Request') != '1':
        raise HTTPException(403,'请求缺少安全校验，请刷新页面后重试')
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/') != settings.frontend_origin.rstrip('/'):
        raise HTTPException(403,'不允许的请求来源')


def require_student(request: Request, db: Session=Depends(get_db)) -> Student:
    csrf(request)
    token=request.cookies.get(COOKIE,'')
    session=db.scalar(select(LoginSession).where(LoginSession.token_hash==hashlib.sha256(token.encode()).hexdigest())) if token else None
    if session is None or aware(session.expires_at)<=now():
        raise HTTPException(401,'登录已失效，请重新登录')
    student=db.get(Student,session.student_id)
    if student is None or not student.is_active:
        raise HTTPException(401,'账号不可用')
    return student


def create_session(db, student_id, response: Response):
    token=secrets.token_urlsafe(32)
    db.execute(delete(LoginSession).where(LoginSession.student_id==student_id,LoginSession.expires_at<=now()))
    db.add(LoginSession(student_id=student_id,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=now()+timedelta(days=7)))
    response.set_cookie(COOKIE,token,max_age=604800,httponly=True,secure=settings.cookie_secure,samesite='lax',path='/')


def require_admin(request: Request):
    provided=request.headers.get('X-Admin-Key','')
    if not settings.admin_api_key or not hmac.compare_digest(provided,settings.admin_api_key):
        raise HTTPException(403,'此接口仅供管理员使用')
