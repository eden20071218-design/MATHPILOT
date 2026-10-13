"""Actual HTTP integration against the running Next.js proxy and FastAPI.
Only creates synthetic local test accounts; no pre-existing records are changed.
"""
import argparse
import secrets
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://localhost:3000/api/v1')
    parser.add_argument('--allow-demo-writes',action='store_true')
    args=parser.parse_args()
    if not args.allow_demo_writes or urlsplit(args.base_url).hostname not in ('localhost','127.0.0.1'):
        parser.error('仅允许本机合成数据验收，须传入 --allow-demo-writes')
    headers={'X-MathPilot-Request':'1'}
    today=datetime.now(ZoneInfo('Asia/Shanghai')).date()
    password=secrets.token_urlsafe(24)
    with httpx.Client(base_url=args.base_url,headers=headers,timeout=40) as client:
        def call(method,path,**kwargs):
            response=client.request(method,path,**kwargs);response.raise_for_status()
            return response.json() if response.status_code!=204 else None
        user=call('POST','/auth/register',json={'email':f'http-demo-{uuid4().hex}@example.test','password':password,'display_name':'HTTP联调模拟学生'})
        assert call('GET','/student/overview')['tasks']==[]
        call('PUT','/student/settings',json={'display_name':'HTTP联调模拟学生','target_score':80,'full_score':100,
            'target_date':(today+timedelta(days=20)).isoformat(),'daily_minutes':60,'study_start':'19:00',
            'reminders':{'timezone':'Asia/Shanghai','quiet_start':None,'quiet_end':None}})
        points=call('GET','/student/overview')['knowledge']
        assert points,'请先运行 python -m app.student_demo 初始化示例目录'
        payload={'request_key':'http-demo-exam','title':'HTTP合成测试考试','exam_date':today.isoformat(),'total_score':100,'achieved_score':60,
            'parts':[{'label':'合成综合题','score':60,'max_score':100,'knowledge_point_ids':[p['id'] for p in points[:2]]}]}
        exam=call('POST','/student/exams',json=payload)
        assert call('POST','/student/exams',json=payload)['duplicate']
        plan=call('POST','/student/planning',json={})
        task=plan['tasks'][0]
        call('POST',f"/student/tasks/{task['id']}/action",json={'action':'start'})
        call('POST',f"/reminders/tasks/{task['id']}/feedback",json={'request_key':'http-demo-feedback','score_rate':0.7,'duration_minutes':20})
        assert call('GET',f"/student/tasks/{task['id']}")['task']['status']=='completed'
        assert client.get('/students').status_code==403
        with httpx.Client(base_url=args.base_url,headers=headers,timeout=40) as other:
            other.post('/auth/register',json={'email':f'http-isolation-{uuid4().hex}@example.test','password':password,'display_name':'隔离验收模拟学生'}).raise_for_status()
            assert other.get(f"/student/tasks/{task['id']}").status_code==404
            assert other.get(f"/student/exams/{exam['exam_id']}").status_code==404
            assert other.get('/student/overview').json()['exams']==[]
        call('POST','/auth/logout')
        assert client.get('/student/overview').status_code==401
    print('PASS: Next.js同源代理 → FastAPI → 数据库；注册/目标/多标签成绩/幂等/规划/反馈/双账号隔离/注销。')
    print('已留下两个明确标注的本地合成测试账号；不修改或删除原有数据。')


if __name__=='__main__':main()
