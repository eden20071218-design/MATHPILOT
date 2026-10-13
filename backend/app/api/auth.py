import hashlib
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.schemas.knowledge import StrictModel
from app.models.entities import Student
from app.models.auth import StudentAccount, LoginSession
from app.db.session import get_db
from app.core.auth import COOKIE, csrf, require_student, password_hash, verify_password, create_session, now, aware

router=APIRouter(prefix='/auth',tags=['Student authentication'],dependencies=[Depends(csrf)])


class Credentials(StrictModel):
    email: str=Field(min_length=3,max_length=320)
    password: str=Field(min_length=10,max_length=128)

    @field_validator('email')
    @classmethod
    def valid_email(cls,value):
        value=value.strip().lower()
        if value.count('@')!=1 or not all(value.split('@')) or any(c.isspace() for c in value):
            raise ValueError('请输入有效邮箱')
        return value


class Registration(Credentials):
    display_name: str=Field(min_length=1,max_length=100)


def public(student):
    return {'id':student.id,'display_name':student.display_name,'email':student.email,'timezone':student.timezone}


@router.post('/register',status_code=201)
def register(data: Registration,response: Response,db: Session=Depends(get_db)):
    student=Student(email=data.email,display_name=data.display_name.strip() or '同学')
    try:
        db.add(student);db.flush()
        db.add(StudentAccount(student_id=student.id,password_hash=password_hash(data.password),preferences={}))
        create_session(db,student.id,response);db.commit()
    except IntegrityError as exc:
        db.rollback();raise HTTPException(409,'无法注册此邮箱，请尝试登录或联系管理员') from exc
    return public(student)


@router.post('/login')
def login(data: Credentials,response: Response,db: Session=Depends(get_db)):
    student=db.scalar(select(Student).where(Student.email==data.email))
    account=db.scalar(select(StudentAccount).where(StudentAccount.student_id==student.id).with_for_update()) if student else None
    if account and account.locked_until and aware(account.locked_until)>now():
        raise HTTPException(429,'尝试次数过多，请15分钟后重试')
    if account is None or not student.is_active or not verify_password(data.password,account.password_hash):
        if account:
            account.failed_logins+=1
            if account.failed_logins>=5:
                account.locked_until=now()+timedelta(minutes=15);account.failed_logins=0
            db.commit()
        else:
            password_hash(data.password,'unregistered-timing-salt')
        raise HTTPException(401,'邮箱或密码不正确')
    account.failed_logins=0;account.locked_until=None
    create_session(db,student.id,response);db.commit()
    return public(student)


@router.get('/me')
def me(student=Depends(require_student)):
    return public(student)


@router.post('/logout',status_code=204)
def logout(request: Request,response: Response,db: Session=Depends(get_db)):
    fingerprint=hashlib.sha256(request.cookies.get(COOKIE,'').encode()).hexdigest()
    db.execute(delete(LoginSession).where(LoginSession.token_hash==fingerprint));db.commit()
    response.delete_cookie(COOKIE,path='/')


@router.post('/logout-all',status_code=204)
def logout_all(response: Response,student=Depends(require_student),db: Session=Depends(get_db)):
    db.execute(delete(LoginSession).where(LoginSession.student_id==student.id));db.commit()
    response.delete_cookie(COOKIE,path='/')
