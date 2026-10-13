# MathPilot

MathPilot 是面向数学学习的智能规划应用，现包含完整学生端页面、账号会话、成绩与知识画像、LangGraph 学习规划、任务反馈及 Web Push 提醒模块。使用 Next.js、React、TypeScript、Tailwind CSS、FastAPI、SQLAlchemy、Alembic 和 Docker Compose。

**首次使用请阅读 [学生端启动、联调与部署说明](docs/student-web.md)**。旧管理 API 现须 `X-Admin-Key`，学生端使用 HttpOnly 会话 Cookie；不再允许匿名访问全部学生记录。

## 本地启动

```bash
docker compose up --build
```

- 前端：http://localhost:3000
- API：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

## 后端开发

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
pytest
uvicorn app.main:app --reload
```

默认连接 PostgreSQL。测试通过依赖覆盖使用临时 SQLite 数据库。

## 数学知识库

已支持文本/Markdown 结构化解析、来源追溯、别名去重、版本修订和人工审核发布。参阅 [知识库导入说明](docs/knowledge-import.md)。API 前缀为 `/api/v1/knowledge`。

服务启动后可运行 `python examples/import_knowledge.py`（在 backend 目录），导入自编函数/导数示例并验证重复请求不会新增数据。解析器本地运行，不需要 AI API 密钥。

## 成绩诊断

`/api/v1/diagnoses/preview` 提供不写库的统计诊断；`/api/v1/diagnoses/from-exam` 从已完成考试和历史记录生成可追溯报告并更新掌握度历史。参阅 [诊断说明](docs/diagnosis.md) 和 [示例报告](docs/example-diagnosis-report.md)。在 backend 目录运行 `python examples/diagnose_exam.py` 可直接输出合成示例 JSON。

## 学习规划

LangGraph 工作流提供 `/api/v1/planning/preview` 和 `/api/v1/planning/runs`，支持依赖优先、时间约束、间隔复习、阶段测验及保留锁定任务的重排。详见 [规划说明](docs/planning.md)。在 backend 目录运行 `python examples/plan_learning.py --summary` 查看模拟结果。

## 提醒与反馈

已加入 Celery + Redis 调度、Web Push 订阅与 Service Worker、免打扰/时区、任务改期和幂等反馈重排。配置 VAPID 后，在学生端 `/settings` 管理提醒；旧 `/reminders` 自动转到设置页。模块架构见 [提醒与反馈说明](docs/reminders.md)，最新身份认证与部署步骤以 [学生端说明](docs/student-web.md) 为准。关闭网页后的真实推送验收仍未完成。

