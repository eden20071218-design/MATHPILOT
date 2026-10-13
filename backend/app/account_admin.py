"""Provision a first password for an existing student without changing their data."""
import argparse
import getpass
from uuid import UUID
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.entities import Student
from app.models.auth import StudentAccount
from app.core.auth import password_hash


def provision(db,student_id,password):
    student=db.get(Student,student_id)
    if student is None or not student.is_active: raise ValueError('学生不存在或已停用')
    if db.scalar(select(StudentAccount).where(StudentAccount.student_id==student_id)):
        raise ValueError('账号已存在；此命令不会覆盖密码')
    if not 10<=len(password)<=128: raise ValueError('密码须为10至128字符')
    db.add(StudentAccount(student_id=student_id,password_hash=password_hash(password),preferences={}))
    db.commit()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--student-id',type=UUID,required=True)
    args=parser.parse_args()
    password=getpass.getpass('设置初始密码（不会显示）：')
    if password!=getpass.getpass('再次输入：'): parser.error('两次密码不一致')
    try:
        with SessionLocal() as db: provision(db,args.student_id,password)
    except ValueError as exc: parser.error(str(exc))
    print('账号已开通，学生可使用原邮箱登录；原有成绩和计划保持不变。')


if __name__=='__main__': main()
