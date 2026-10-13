# MathPilot 学生端：运行、联调与部署

## 本次交付

复用原有知识库、统计诊断、LangGraph 规划与 Celery/Web Push 服务，新增学生身份和专用 API，没有重建业务数据库。仓库未找到 `AGENTS.md`，按实际存在的 `AFENT.md` 执行。

| 页面 | 地址 | 可实际操作的功能 |
| --- | --- | --- |
| 注册 / 登录 | `/login` | 创建账号、登录、错误提示、过期会话重新登录 |
| 学生首页 | `/` | 目标、真实最近成绩、下一任务、完成率、手动刷新 |
| 成绩管理 | `/exams` | 总分、逐题/独立知识点得分、多标签、总分校验、明细、自动诊断、幂等提交 |
| 知识画像 | `/knowledge` | 掌握度估计、置信度、证据数量、历史趋势与来源、搜索 |
| 学习日历 | `/calendar` | 日/周切换、日期跳转、每日用时、时区、状态、任务入口 |
| 任务详情 | `/tasks/{id}` | 练习要求、完成标准、难度、开始/锁定、反馈、改期/延期/取消 |
| AI 规划解释 | `/plan` | 生成/重排、优先级因素、前置作用、调整原因、未能安排的内容 |
| 学习报告 | `/reports` | 考试得分率趋势、诊断与证据、任务完成、阶段及每周进度 |
| 设置 | `/settings` | 目标、每天时长/起始时刻、时区、免打扰、推送、隐藏分数、导出、退出全部设备 |

设计使用冷白演算纸与墨蓝配色、宋体标题、系统中文正文字体。没有外部字体、广告分析或生成的假成绩。电脑为侧栏布局，手机为可横滑导航和单列内容；包含键盘焦点、跳过导航、aria 状态、减少动画支持。

## 方式一：本机快速启动（不需要 Docker）

需要 Python 3.11+、Node.js 22+、pnpm 11.25.0。以下 PowerShell 命令在项目根目录开始；不要覆盖已有 `.env` 或生产数据库。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:DATABASE_URL='sqlite:///./student-web-demo.db'
$env:FRONTEND_ORIGIN='http://localhost:3000'
.\.venv\Scripts\python.exe -m alembic upgrade head
# 可选：只创建带“示例”标记的知识目录，不生成用户成绩。
.\.venv\Scripts\python.exe -m app.student_demo
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

第二个终端：

```powershell
cd frontend
# 未安装 pnpm 时：npm install --global pnpm@11.25.0
pnpm install --frozen-lockfile
pnpm dev --hostname 127.0.0.1
```

打开 **http://localhost:3000**。请统一使用 localhost，不要将 127.0.0.1 与 localhost 混用；Origin 必须与后端配置匹配。前端通过同源 `/api/v1/*` 代理到后端，不把管理密钥交给浏览器。只有需要改变后端位置时才设置 `INTERNAL_API_URL`，该值在 Next.js 构建时用于代理规则。

注册账号 → 设置目标/考试日期 → 录入成绩与标签 → 生成计划 → 日历点击任务 → 提交反馈 → 查看画像和报告。没有成绩时不会虚构当前分数；没有知识目录时会显示明确引导。示例目录只用于功能演示；正式教学请导入并审核教材知识点。

生产模式的本机检查：先停止开发服务，再运行 `pnpm build` 与 `pnpm start --hostname 127.0.0.1`。不要让开发与构建同时写同一个 `.next` 目录。

此快速路径支持同步学生业务。**SQLite 不替代 PostgreSQL 并发语义；未启动 Redis、worker、beat 时，后台推送与排队重规划不会执行。** 页面会明确显示排队或错误状态，不把页面轮询称为推送。

## 方式二：Docker Compose 全组件

需要 Docker Desktop（Linux 容器）或 Linux Docker Engine。

1. 参考 `.env.example` 创建根目录 `.env`，保留已有数据库配置。将数据库密码改为强密码，并同步更新 `DATABASE_URL` 中的密码（特殊字符需要 URL 编码）。
2. 生成 VAPID、提醒令牌签名和管理 API 密钥：

```bash
docker compose build backend
docker compose run --rm --no-deps backend python -m app.reminder_cli keys
```

3. 把输出的四个值写入 `.env`，保持私密；将 `VAPID_SUBJECT` 改为有效的管理员联系邮箱。普通 Cookie 注册登录不依赖这些密钥，但管理接口/Web Push/旧 CLI 令牌分别需要对应配置。
4. 启动：

```bash
docker compose up --build -d
docker compose ps
docker compose logs backend worker beat
# 可选示例目录
docker compose exec backend python -m app.student_demo
```

访问 http://localhost:3000；API 健康检查 http://localhost:8000/health，OpenAPI http://localhost:8000/docs。PostgreSQL/Redis 不公开端口；前后端主机端口默认只绑定 127.0.0.1。backend 启动时执行 `alembic upgrade head`；worker/beat 等待后端与 Redis 健康。Beat 保持单实例。

`frontend/Dockerfile` 使用 pnpm 锁文件，Linux standalone 输出；`sw.js` 随 public 目录一起复制。pnpm 明确禁用未使用的 sharp 构建脚本，不要求本机授予符号链接权限。

## HTTPS 部署参考

仓库提供可选 `docker-compose.prod.yml` 和 `deploy/Caddyfile`，未实际部署到公网。将域名解析到服务器，在 `.env` 中设置：

```dotenv
MATHPILOT_DOMAIN=math.example.com
FRONTEND_ORIGIN=https://math.example.com
PUBLIC_API_URL=https://math.example.com/api/v1
COOKIE_SECURE=true
```

保留 Compose 内部 API 地址 `http://backend:8000`，不要把它作为浏览器可访问地址。启动 HTTPS 入口：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

仅让反向代理的 80/443 对外可达；学生页面与 API 同域。Caddy 自动申请证书，需要正确 DNS 和可达端口。上线前另行落实：反向代理注册/登录/IP 限流、账号恢复与邮箱验证、管理员权限细分/密钥轮换、审计、数据库备份与恢复演练、依赖漏洞扫描、数据保留和隐私政策。此版本为基本认证，**没有 MFA、邮件验证或自助密码找回**，不应宣称已通过生产安全认证。

## 身份、权限与迁移

- 密码采用随机盐 scrypt，数据库不存明文。会话为随机 256-bit+ opaque token，数据库只存 SHA-256 摘要；Cookie 为 HttpOnly、SameSite=Lax，生产启用 Secure，有效期 7 天。
- 注销使当前会话立即失效，“退出所有设备”撤销该学生所有 Cookie 会话。管理员以前签发的 Bearer 提醒令牌属于独立认证机制，不受 Cookie 注销影响；不要向学生网页分发这些令牌。
- 写请求必须有 `X-MathPilot-Request: 1`；若存在 Origin，须与 `FRONTEND_ORIGIN` 完全匹配。CORS 仅允许配置的前端来源。个人 API 返回 `Cache-Control: no-store`。
- 学生 ID 始终从会话获取。详情和写操作按所属学生查找，访问其他学生资源返回 404；普通账号不能调用管理接口。课程目录共享，草稿教材、未审核修订、他人的题目/成绩不对学生暴露。
- 旧 `/students` 等 CRUD、`/knowledge/*`、`/diagnoses/*`、`/planning/*` 现在统一要求 `X-Admin-Key`。未设置 `ADMIN_API_KEY` 时默认拒绝管理访问，不保留匿名旁路。既有管理脚本需加此请求头，知识导入示例已更新。
- 连续 5 次错误密码锁定已有账号 15 分钟；仍需部署层 IP/注册限流避免资源滥用。
- 新迁移 `20261013_0006` 添加 StudentAccount（student_id 唯一）、LoginSession（token_hash 唯一）、ExamSubmission（学生+请求键唯一、exam_id 唯一）。父 Student/Exam 删除时按外键级联，升级不会为现有学生设置共享默认密码。

已有 Student 记录不能被同邮箱公开注册冒领。管理员可为指定旧学生开通**第一次**密码（命令不会覆盖已有密码）：

```bash
docker compose exec backend python -m app.account_admin --student-id <已有学生UUID>
```

密码通过交互提示输入，不应写入命令行参数或日志。原学生 ID、成绩和计划保持不变。

## 学生 API

前缀 `/api/v1`。网页不需要发送 student_id；未知字段被 Pydantic 拒绝。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/auth/register`、`/auth/login` | 建立 Cookie 会话 |
| GET | `/auth/me` | 当前学生 |
| POST | `/auth/logout`、`/auth/logout-all` | 撤销当前 / 全部浏览器会话 |
| GET | `/student/overview` | 当前学生首页、任务、考试、画像、规划、诊断、偏好 |
| POST | `/student/exams` | 原子保存多标签考试并调用既有诊断服务，request_key 幂等 |
| GET | `/student/exams/{id}` | 本人成绩明细 |
| GET | `/student/tasks/{id}` | 本人任务、完成标准、练习历史 |
| POST | `/student/tasks/{id}/action` | start / lock / unlock |
| PUT | `/student/settings` | 目标、时间、显示与提醒偏好 |
| POST | `/student/planning` | 从服务端本人数据构造 LangGraph 输入，保存规划 |
| GET | `/student/export` | 导出本人学习记录；排除密码、会话和推送 endpoint 凭据 |
| GET / PUT | `/reminders/settings` | Cookie 或旧管理员签发的 Bearer 令牌 |
| POST / DELETE | `/reminders/subscriptions[/{id}]` | 本人浏览器推送订阅 |
| POST | `/reminders/tasks/{id}/feedback` | 完成任务、画像历史与必要重排事件 |
| POST | `/reminders/tasks/{id}/schedule` | 延期、取消、改期，校验预算与冲突 |
| GET | `/reminders/feedback/{id}`、`/reminders/deliveries` | 本人重排和投递状态 |

页面范围：概览最近 100 场考试、1000 项任务、200 个可用知识点、每知识点最多 20 条历史（最近 5000 条状态内）；报告明确显示范围。导出另查询完整的本人考试、任务、画像、规划、诊断和练习历史。大规模生产部署需要分页/异步导出，不能用本版小规模聚合接口承担无限数据量。

画像不是校准掌握概率；未测知识点显示“尚未观察”。规划使用中性先验及高不确定性，不将先验显示为已有成绩。考试诊断与练习反馈当前未融合成一个测量模型，UI 标明来源且不跨来源比较增减。没有作答证据时失分原因保留未知。调整目标/时间后需主动重新规划，不静默移动已有任务。

## 自动化与联调

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
# 需已启动前后端、初始化示例目录；会新增两个本机合成测试账号。
.\.venv\Scripts\python.exe examples/student_workflow.py --allow-demo-writes
```

```bash
cd frontend
pnpm test
pnpm build
```

验收记录（2026-10-13）：

- 后端 pytest：76 项通过（包括旧 65 项）。覆盖注册、密码存储、Cookie、CSRF/Origin、失效/伪造/停用会话、锁定、注销、旧账号防冒领、设置、成绩一致性、多标签分摊、幂等、完整规划反馈与双学生越权访问。
- 前端 Node 测试：7 项通过。覆盖 API Cookie/CSRF/no-store、401、422、网络失败、204、时区/DST、无 window/document 的 Service Worker 去重。
- Next.js 15.5.27 production build：成功，包含 TypeScript 检查，全部学生页面成功构建。已启动生产前端配合独立 SQLite 后端联调。
- 真实 HTTP 脚本：通过 Next.js 同源代理执行注册→目标→多标签成绩→幂等重试→规划→反馈→第二账号越权拒绝→注销，全部通过。
- 真实浏览器：注册、空状态、目标保存、总分错误提示/纠正、规划解释、任务锁定/开始/完成、画像更新及报告页已检查。桌面与 390px 手机尺寸检查；首页及六个主要列表/设置页无整页横向溢出。开发时仅观察到热更新整页重载提示，无应用运行时错误。
- 原有数据库未用于联调。新增的 `backend/student-web-demo.db` 是独立合成数据；浏览器里标注“联调演示同学”的成绩不是用户真实成绩。该数据库被 `.gitignore` 排除。
- 尚未验证：Docker 容器构建/整套启动、真实 PostgreSQL 行锁并发、Redis worker/beat 联调、HTTPS 域名部署、关闭网页后的真实推送。当前机器没有 Docker/Redis，本次未安装系统软件或部署公网。推送代码测试不等于实际通知已到达。

## 主要目录

```text
backend/
  app/api/auth.py               注册登录与会话撤销
  app/api/student.py            当前学生聚合与业务 API
  app/core/auth.py              密码、Cookie、CSRF、管理接口保护
  app/models/auth.py            账号、会话、考试提交幂等表
  app/account_admin.py          旧学生首次开通账号
  app/student_demo.py           幂等示例课程目录
  alembic/versions/20261013_0006_student_auth.py
  examples/student_workflow.py  真实 HTTP 联调脚本
  tests/test_student_web.py
frontend/
  app/                         八类学生页面与登录入口
  components/                  统一外壳、页面、设置、任务反馈
  lib/api.ts                   同源请求、错误处理与时区工具
  lib/types.ts                 学生端 TypeScript 契约
  tests/                       API 与 Service Worker 测试
deploy/Caddyfile
docker-compose.yml
docker-compose.prod.yml
docs/screenshots/student-desktop.jpg
docs/screenshots/student-mobile.jpg
```

界面验收截图仅保存在本地 `docs/screenshots/`，不随公开源码上传，以避免后续截图意外包含学生信息。
