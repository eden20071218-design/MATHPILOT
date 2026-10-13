"""Explicitly opt-in local sample catalog. Does not create student scores or accounts."""
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.entities import KnowledgePoint, KnowledgeDependency


def main():
    names=[('DEMO-FUNCTION','函数（示例）'),('DEMO-LIMIT','极限（示例）'),('DEMO-DERIVATIVE','导数（示例）')]
    with SessionLocal() as db:
        points=[]
        for code,name in names:
            point=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==code))
            if point is None:
                point=KnowledgePoint(code=code,name=name,description='本地界面联调的示例目录，不是已审核的完整课程。');db.add(point);db.flush()
            points.append(point)
        for a,b in zip(points,points[1:]):
            if db.scalar(select(KnowledgeDependency).where(KnowledgeDependency.prerequisite_id==a.id,KnowledgeDependency.dependent_id==b.id)) is None:
                db.add(KnowledgeDependency(prerequisite_id=a.id,dependent_id=b.id))
        db.commit()
        print('示例目录已就绪：函数 → 极限 → 导数。未创建学生、成绩或练习记录。')


if __name__=='__main__':main()
