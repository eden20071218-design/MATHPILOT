"""Local administration: generate VAPID environment values or issue a scoped token."""
import argparse
import base64
import secrets
from uuid import UUID
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from app.core.reminder_auth import issue_token


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command', choices=['keys','token','demo'])
    parser.add_argument('--student-id',type=UUID)
    args=parser.parse_args()
    if args.command == 'keys':
        vapid=Vapid(); vapid.generate_keys()
        private=vapid.private_key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        public=vapid.public_key.public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        print('VAPID_PRIVATE_KEY='+base64.urlsafe_b64encode(private).decode().rstrip('='))
        print('VAPID_PUBLIC_KEY='+base64.urlsafe_b64encode(public).decode().rstrip('='))
        print('REMINDER_API_SECRET='+secrets.token_urlsafe(48))
        print('ADMIN_API_KEY='+secrets.token_urlsafe(48))
    elif args.command == 'demo':
        seed_demo()
    elif args.student_id:
        print(issue_token(args.student_id))
    else:
        parser.error('token requires --student-id')


def seed_demo():
    """Create only explicitly synthetic data; repeated runs do not duplicate it."""
    import json
    from datetime import timedelta
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.entities import Student, KnowledgePoint, LearningGoal, LearningPlan, LearningTask
    from app.services.reminders import now_utc, sync_task
    with SessionLocal() as db:
        student=db.scalar(select(Student).where(Student.email=='push-demo@mathpilot.invalid'))
        if student is None:
            student=Student(email='push-demo@mathpilot.invalid',display_name='推送验收模拟学生');db.add(student);db.flush()
        kp=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code=='PUSH-DEMO-FUNCTION'))
        if kp is None:
            kp=KnowledgePoint(code='PUSH-DEMO-FUNCTION',name='函数（推送演示）');db.add(kp);db.flush()
        goal=db.scalar(select(LearningGoal).where(LearningGoal.student_id==student.id,LearningGoal.title=='推送验收演示目标'))
        if goal is None:
            goal=LearningGoal(student_id=student.id,title='推送验收演示目标',target_date=(now_utc()+timedelta(days=30)).date(),daily_minutes=60);db.add(goal);db.flush()
            plan=LearningPlan(student_id=student.id,goal_id=goal.id,name='推送验收演示计划',version=1,status='active');db.add(plan);db.flush()
            start=now_utc()+timedelta(minutes=15)
            task=LearningTask(plan_id=plan.id,knowledge_point_id=kp.id,title='完成5道函数定义练习',sequence=1,
                scheduled_start=start,due_at=start+timedelta(minutes=20),estimated_minutes=20,status='scheduled')
            db.add(task);db.flush();sync_task(db,task)
        else:
            plan=db.scalar(select(LearningPlan).where(LearningPlan.goal_id==goal.id))
            task=db.scalar(select(LearningTask).where(LearningTask.plan_id==plan.id))
        db.commit()
        print(json.dumps({'student_id':str(student.id),'task_id':str(task.id),
            'instruction':'使用 token --student-id 签发令牌；演示计划无 PlanningRun，需自动重排时会提示人工处理'},ensure_ascii=False))


if __name__ == '__main__':
    main()
