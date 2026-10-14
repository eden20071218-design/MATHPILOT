# Railway 试用部署

部署日期：2026-10-14。仅使用用户确认的 Trial 额度，不升级付费套餐。

- 网站：https://frontend-production-0e0d.up.railway.app
- 控制台：https://railway.com/project/262b6315-f542-4e8b-9dfa-6d1156aea27a
- 源码：https://github.com/eden20071218-design/MATHPILOT

## 配置

五个服务：frontend、backend、scheduler、Postgres、Redis。仅 frontend 暴露 HTTPS 域名。数据库及 Redis 通过平台模板生成独立密码并使用持久卷，不建立公开 TCP 代理。

前端根目录 `/frontend`，使用 Dockerfile；`HOSTNAME=0.0.0.0`、`PORT=3000`、构建变量 `INTERNAL_API_URL=http://backend.railway.internal:8000`。后端根目录 `/backend`，`PORT=8000`，健康检查 `/health`，先执行 Alembic 迁移和幂等示例知识目录初始化，再启动 uvicorn。该示例目录不是完整教材知识库，不生成学生成绩。

后端和 scheduler 使用 `postgresql+psycopg` 连接串、Redis 内网变量引用。`COOKIE_SECURE=true`，`FRONTEND_ORIGIN` 与网站 HTTPS 地址一致。管理 API 密钥保持未配置，管理接口默认拒绝访问；推送密钥仅存在平台环境变量中，不提交到源码。

为满足试用版五服务上限，scheduler 采用单副本 Celery worker + 内嵌 beat，命令：

```sh
celery -A app.celery_app:celery_app worker --beat --loglevel=INFO --concurrency=1 --schedule=/tmp/celerybeat-schedule
```

不可扩容这个合并服务为多副本。调度扫描发生在数据库迁移前时可能短暂报表不存在；迁移完成后扫描会恢复。提醒和重排由数据库 outbox 保证持久性，beat 本地文件不是业务数据源。

## 费用和数据

用户提供的套餐截图显示 Trial、30 天或 $5。这是有期限和额度的试用，不保证长期在线。没有开通付费订阅或绑定支付方式。不要升级或充值，除非用户另行授权。额度耗尽、试用结束或平台回收持久卷可能造成停机或数据丢失，因此试用期间不要将本站当作唯一的正式学生档案库。重要记录应使用设置页导出并妥善保存。

本地数据库、教材、截图和私密环境文件未上传。独立云数据库仅包含示例目录，以及明确标记的合成验收账号（若执行下面的验收命令）。

## 验收

2026-10-14 实测：五个服务均为 SUCCESS；公开 HTTPS 登录页返回 200；完整远程验收脚本通过；本地后端回归 76 项通过。后台 beat 每 15 秒扫描由 worker 正常执行。没有完成关闭网页后的实际推送验收。

远程写入验收需要两个显式开关，只能用于自己授权的 HTTPS 环境。每次运行新增两个合成测试账号，不修改其他账号：

```powershell
cd backend
.\.venv\Scripts\python.exe examples/student_workflow.py --base-url https://frontend-production-0e0d.up.railway.app/api/v1 --allow-demo-writes --allow-remote-demo-writes
```

此脚本覆盖注册、目标、多标签成绩、幂等、规划、任务反馈、双账号越权拒绝、注销。后台扫描成功不等于浏览器实际收到推送；关闭网页后的真实通知仍需浏览器授权及设备验收。
