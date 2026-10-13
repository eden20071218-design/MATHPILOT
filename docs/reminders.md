# 提醒与学习反馈

> 学生端版本更新：浏览器界面已改用注册/登录后的 HttpOnly Cookie，入口为 `/settings`，不再手动粘贴学生令牌。下面保留此前提醒模块的实现记录；最新启动、安全配置与测试结果以 [学生端说明](student-web.md) 为准。旧通用管理 API 现已加 `X-Admin-Key` 保护。

## 运行方式

后台路径为 `Celery Beat → Redis → Celery worker → Web Push 服务 → 浏览器 Service Worker → 系统通知`。网页不参与定时发送，无页面轮询；Beat 每 15 秒扫描数据库 outbox。开始、复习提醒容许 60 秒调度迟延，超过则取消；逾期提醒每个截止时间发送一次，不循环骚扰。

先安装 Docker Desktop 并启用 Linux 容器。在项目根目录按 `.env.example` 创建 `.env`，保留已有配置。生成密钥：

```bash
docker compose build backend
docker compose run --rm --no-deps backend python -m app.reminder_cli keys
```

将输出的 `VAPID_PRIVATE_KEY`、`VAPID_PUBLIC_KEY`、`REMINDER_API_SECRET` 写入 `.env`，不要提交、截图或发给别人。将 `VAPID_SUBJECT` 设为自己的有效联系邮箱（`mailto:` 格式），密钥更新会要求浏览器重新订阅。然后：

```bash
docker compose up --build -d
docker compose exec backend python -m app.reminder_cli demo
docker compose exec backend python -m app.reminder_cli token --student-id <上一步student_id>
docker compose logs worker beat
```

`demo` 只创建明确标注的模拟学生和任务，重复运行复用已有记录，不删除或重设用户数据。演示任务是手工计划，无 LangGraph 规划快照；低分触发重排时会记录 `needs_attention`。真实 `/planning/runs` 生成的计划可以自动重排。

打开 `http://localhost:3000/reminders`，输入学生令牌（有效期一天，只保存在页面内存），点击“开启后台推送”，允许浏览器通知。API 文档在 `http://localhost:8000/docs`。Compose 只绑定本机回环地址；数据库和 Redis 不发布主机端口。

非 Docker 开发：在 backend 安装 `pip install -e ".[dev]"`，配置 PostgreSQL/Redis 环境变量，执行 `alembic upgrade head`，分别运行：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
celery -A app.celery_app:celery_app worker --loglevel=INFO
celery -A app.celery_app:celery_app beat --loglevel=INFO
```

Celery 运行环境推荐 Linux/Compose；本机 Windows 前端 `pnpm build`、`pnpm start` 不使用 standalone，Linux Docker 构建保留 standalone。`public/sw.js` 已复制进容器。只启动前后端、不启动 Redis/worker/beat，不会发送定时推送。

## 必须人工完成的真实关闭页面验收

1. 确认 worker、beat、Redis 健康；使用真实 Chrome 普通窗口（非模拟推送）。
2. 开启 Web Push，通知权限为 granted；系统通知允许 Chrome。确保网络可达浏览器的推送服务。
3. 临时关闭应用的免打扰时段并保存（测试完成后恢复个人设置）。点击“一分钟后的测试推送”，记下 `reminder_id` 与发送时间。
4. 关闭本网站所有标签页，保留浏览器运行。不要点击出现的通知，先观察是否实际收到。
5. 收到后重新打开提醒页、输入令牌，手动查看回执，核对同一 reminder 的 `accepted_at`、`displayed_at` 非空且 `open_windows = 0`。保存通知截图与脱敏回执、worker 日志作为证据。

`accepted` 只代表推送服务接受；`displayed` 代表 Service Worker 的 `showNotification` 成功返回，不代表人已看到。系统免打扰仍可能隐藏弹窗，须结合人工观察。没有回执可能是网络回传失败，不能断言未展示。设备休眠、离线、浏览器完全退出、供应商网络受阻都可能延迟或丢失 TTL=300 秒的推送。关闭网页不等于退出浏览器。

**当前真实验收：未完成。** 本机未找到 Docker/Redis，Chrome 扩展控制连接尚不可用；不能以单元测试、伪造回执或 HTTP 201 代替此项验收。

## API

前缀 `/api/v1/reminders`，除 public-key 和持有随机回执令牌的 receipts 外，均须 `Authorization: Bearer <学生令牌>`。

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET | `/public-key` | VAPID 公钥，缺配置返回 503 |
| GET / PUT | `/settings` | 提前量、时区、免打扰、总开关；同步待发送提醒 |
| POST | `/subscriptions` | 幂等绑定 Web Push endpoint 和加密参数 |
| DELETE | `/subscriptions/{id}` | 停用该学生的浏览器订阅 |
| POST | `/test` | 排队一分钟后的真实推送，每分钟一次 |
| POST | `/receipts` | Service Worker 展示回执，使用不可预测的单投递令牌 |
| GET | `/deliveries` | 最近 100 条设备投递、错误、重试与展示回执 |
| GET | `/inbox` | 当前学生的站内通知 |
| POST | `/tasks/{id}/schedule` | postpone / reschedule / cancel；校验冲突、每日预算、目标日期 |
| POST | `/tasks/{id}/feedback` | 幂等保存练习、完成任务、更新掌握度历史、评估是否重排 |
| GET | `/feedback/{id}` | 查看反馈与重排状态、原因及新 planning_run_id |

反馈示例请求体：

```json
{"request_key":"demo-feedback-001","score_rate":0.4,"difficulty":0.5,"duration_minutes":20,"notes":"函数定义仍需练习"}
```

改期示例请求体（替换成未来时间）：

```json
{"action":"postpone","start":"2026-10-20T19:00:00+08:00","end":"2026-10-20T19:20:00+08:00","reason":"调整可用学习时间"}
```

## 数据关系与约束

新表均使用 UUID 主键、created_at/updated_at；迁移 `20261013_0005`：

- `ReminderPreference.student_id → Student`：唯一，一名学生一份偏好。
- `PushSubscription.student_id → Student`：一对多；`endpoint_hash` 全局唯一，不能将别人的订阅绑定给当前学生。
- `Reminder.student_id → Student`、`task_id → LearningTask`（测试推送可空）：`dedup_key` 唯一，由任务 ID、类型、时间锚点、提前量确定；有 due_at、available_at、状态、抢占租约、错误。
- `PushDelivery.reminder_id → Reminder`、`subscription_id → PushSubscription`：组合唯一，一次提醒每设备一条投递；独立记录尝试次数、失败、accepted/displayed 时间；`receipt_token` 唯一。
- `FeedbackEvent.student_id → Student`、`task_id → LearningTask`、`attempt_id → TaskAttempt`：`(student_id, request_key)` 唯一，同键异内容返回 409；保存重排原因、冻结请求、重试次数与状态。
- 删除父项按外键级联；任务取消不删历史，失效提醒标记 cancelled。旧 ExamQuestion 两个同名唯一约束已分别命名为 `uq_exam_question` 和 `uq_exam_position`，迁移兼容已有 SQLite 数据。

## 一致性与安全边界

计划保存、任务改期/取消/完成、偏好变更同步 outbox；暂停计划停止提醒，恢复时重建待发项；定时扫描也会核对已有状态。发送前重新检查任务、时间、偏好，旧队列项不会按旧日程发送。被新计划保留的旧任务 ID 继续有效。时区使用 IANA ZoneInfo，存储 UTC，跨午夜免打扰及 DST 有测试。

数据库条件更新租约避免并行消费者同时领取；设备已 accepted 的投递不随失败设备重试。失败指数退避，最多 5 次；404/410 停用订阅，其他不可重试 4xx 终止。错误文本不存 endpoint 密钥；请求限制 HTTPS 供应商域名且拒绝重定向。Service Worker 按稳定 tag 和持久缓存去重（保留最近 500 条）。

Web Push 外部发送与数据库不能原子提交：进程在发送后、提交前崩溃仍有重投窗口。这里是至少一次调度加端到端幂等去重，不承诺绝对 exactly-once；缓存被清除后仍可能重复显示。Beat 必须单实例。当前为小规模全表校对，规模扩大需索引批处理/事件驱动同步与监控告警。

反馈使用原始练习记录重新估计带先验、难度和时间衰减的掌握度指数；写入历史置信信息，不把一次正确率当真实掌握概率。不把历史画像当新证据重复累计。最近三次至少两次低于 60% 或延迟完成超过一天才排队重排；调用既有 LangGraph 工作流、保留已完成/进行中/锁定任务并记录调整原因。反馈画像当前作用域为任务练习，尚未融合考试画像；它不是 IRT/BKT 的校准概率。

本模块采用管理员本地签发的学生范围令牌，尚非完整登录/账号系统。旧 CRUD/知识库/诊断/规划 API 尚未整体接入授权，**此版本只用于可信本地开发，不可直接暴露公网**。正式部署需统一身份认证/权限、数据库密钥管理、HTTPS、速率限制、订阅静态加密、监控与数据保留策略。推送正文只含通用提醒，不发送成绩或敏感学习内容。

## 测试与文件

```text
backend/app/
  api/reminders.py          # API 与学生范围校验
  core/reminder_auth.py     # 有限时效签名令牌
  models/reminders.py       # 五个新增持久化实体
  schemas/reminders.py      # Pydantic 请求模型
  services/reminders.py     # outbox、时区、重试、Web Push
  services/feedback.py      # 画像更新及持久重排事件
  celery_app.py / jobs.py   # Beat 和 worker
  reminder_cli.py           # 密钥、令牌、幂等模拟数据
backend/alembic/versions/20261013_0005_reminders.py
backend/tests/test_reminders.py
frontend/app/reminders/page.tsx
frontend/public/sw.js
frontend/tests/sw.test.cjs
docker-compose.yml
```

运行 `cd backend && pytest -q`；前端运行 `node --test tests/sw.test.cjs` 和 `pnpm build`。测试覆盖幂等、时区/DST、零提前量、改期、暂停、完成、过期、设备重试、租约、订阅归属、错误脱敏、画像与真实 LangGraph 重排、VAPID 签名与加密请求构造。发送网络和浏览器对象在单元测试中被替身隔离；这些不构成真实 Redis 或关闭标签页推送验收。

2026-10-13 本机验证：pytest **65 passed**，Service Worker **1 passed**，Next.js **15.5.27 production build 成功**（含 TypeScript 检查）。SQLite 迁移从模拟旧同名约束升级至 head、元数据一致性、降级及模拟数据幂等均通过。Docker Compose、真实 PostgreSQL/Redis 并发和 Chrome 关闭网页推送尚未实测。
