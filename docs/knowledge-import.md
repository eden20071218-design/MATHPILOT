# 数学知识库管理与导入

本模块复用第一阶段知识点、前置依赖、题目和多对多关联模型。新增 `material_sources`、`material_imports`、`knowledge_aliases`、`knowledge_revisions` 四张表，通过 Alembic `20261013_0002` 部署。

## 运行示例

在仓库根目录运行 `docker compose up --build`，API 就绪后执行：

```powershell
cd backend
.\.venv\Scripts\python.exe examples/import_knowledge.py
```

也可不用 Docker，在安装后端开发依赖后使用 SQLite：

```powershell
cd backend
$env:DATABASE_URL='sqlite:///./mathpilot.db'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 在第二个终端执行 examples/import_knowledge.py
```

`examples/knowledge.md` 是自编示例，包括函数、导数、别名微商、差商公式、适用条件、前置依赖和关联两个知识点的例题，并非附件教材的摘录。脚本发送两次完全相同的导入请求，打印结构化 JSON，并验证第二次 `duplicate=true`、新增数量为零。例题与依赖在审核发布后建立。

## API（前缀 /api/v1/knowledge）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | /parse | 文本/Markdown → Pydantic 结构化 JSON，不写数据库 |
| POST | /imports | 原始文本解析并原子导入待审核版本 |
| POST | /imports/structured | 校验外部 AI/人工结构化输出并导入 |
| GET | /imports/{id} | 获取原文、解析结果、来源和导入回执 |
| GET | /sources | 来源列表，支持分页 |
| POST | /points | 人工新增结构化知识点，进入待审核 |
| GET | /points?q=微商 | 按名称/别名查询，支持分页 |
| GET | /points/{id} | 别名、已发布内容、全部修订及原文 |
| PATCH | /points/{id} | 新增修订，不覆盖旧版本 |
| GET | /revisions?status=pending | 审核队列，支持分页 |
| POST | /revisions/{id}/review | approved/rejected + reviewer + note |

请求示例：

```json
{
  "source_key": "my-calculus-notes",
  "source_title": "导数学习笔记",
  "source_version": "1",
  "format": "markdown",
  "text": "# 导数\n别名：微商\n定义：差商的有限极限。\n公式：f'(x0)=lim_{h→0}(f(x0+h)-f(x0))/h\n条件：在邻域内有定义，h≠0，极限存在且有限。\n题型：按定义求导\n方法：构造差商并求极限。"
}
```

审核示例：从 `GET /revisions` 取得 UUID 后，提交以下 JSON 到 `/revisions/{id}/review`。这是显式人工审核动作，解析器不会自行批准。

```json
{"status":"approved","reviewer":"数学教师","note":"已核对定义、公式及适用条件"}
```

## 结构化输出和去重规则

`schemas/knowledge.py` 定义 `KnowledgeContent`、`Formula`、`Example`、`ParsedMaterial` 等 Pydantic 模型。字段包括名称、别名、定义、定理、公式、条件、题型、方法、前置知识、例题、原文证据、置信度及审核原因；禁止未知字段，限制字符串长度和集合大小，置信度限定 0–1。

本地规则解析器支持 Markdown 标题、`知识点：名称`、带字段标签的文本，以及简单 `名称是……` 定义。保留未分类文本并标记审核。首版不宣称能完整理解任意教材散文，不进行通用公式正确性证明。公式条件缺失、括号不匹配、除以零和不确定表述触发审核原因，所有导入默认 pending。

名称使用 Unicode NFKC、大小写和空白规范化，显式别名归入同一知识点；不会凭相似名称自动合并。别名冲突回滚整个导入。描述相同的再次导入不会产生新修订；不同描述或来源版本新增修订。未显式声明的同义词需要人工提供别名。数据库唯一约束防止并发写入污染；竞争请求可能返回 409，重试后得到重复回执。

资料原文、来源 URI/版本与结构化推断分别保存。规则解析记录 `ai_generated=false`；外部 AI JSON 必须记录 `ai_generated=true`、`model_name` 和置信信息，不能执行原始资料中的指令。置信度表示提取可靠性，不是数学正确率。

审核前仅建立知识点身份、别名及待审核版本，正式 description、依赖与例题不会发布。审核时检查引用存在性、自依赖和依赖环，题目内容指纹用于跨修订去重，关联表复用已有唯一约束。历史例题/依赖仍保留，新版本审核为追加发布；完整依赖图替换和例题撤回留待后续版本。

第一阶段旧 `/knowledge-points` CRUD 是兼容接口；本模块的来源、审核和版本管理应使用 `/knowledge/points`。当前应用仍是本地开发环境，尚未接入认证和审核者角色授权；reviewer 字段是审计署名，并非已验证身份。

附件 EPUB 暂不自动导入；可将选定章节导出为文本或 Markdown 后使用本接口。PDF、图片、OCR 与 EPUB 适配器保留为后续扩展，当前 API 只接受 text/markdown。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

覆盖重复导入、别名归一、来源版本、历史修订、待审核隔离、例题多对多、前置依赖环、消歧冲突回滚、非法输入、外部 AI 置信校验，以及已有数据库的 Alembic 升降级和模型一致性。
