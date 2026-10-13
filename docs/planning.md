# 个性化数学学习规划

工作流由真实 LangGraph StateGraph 编译运行：START → diagnosis → priority → generate → validate → save → END。预览保留 save 节点但不写库，保存接口在该节点原子写入学习计划、任务和审计快照。无需外部模型或 API 密钥。

## 运行模拟数据

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe examples/plan_learning.py --summary
.\.venv\Scripts\python.exe examples/plan_learning.py
.\.venv\Scripts\python.exe -m pytest -q
```

模拟资料明确为合成数据：55分、目标75分、三周学习期、每日最多60分钟、函数→导数，附练习得分率及历史考试表现。脚本输出阶段目标、周计划、每日分钟数及任务明细；不写入真实学生记录。

## API

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | /api/v1/planning/preview | 接收 PlanningRequest，在内存运行完整工作流 |
| POST | /api/v1/planning/runs | 要求现有 student_id、goal_id、知识点 UUID；保存新计划版本 |
| GET | /api/v1/planning/runs/{id} | 获取版本化输入、计划结果及调整原因 |

模拟请求可由 `examples.plan_learning.sample().model_dump(mode='json')` 获得。所有日期时间使用带时区偏移的 ISO 8601，timezone 为 IANA 名称，默认 Asia/Shanghai。availability 明确每天可用开始和结束时间，daily_minutes 是每天硬上限。即使两个 availability 重叠也不能重复使用时间。不同日期可通过可用时段长度控制实际时间，暂不提供星期重复规则，调用方展开日期。

knowledge 提供 mastery（已有诊断指标）、uncertainty（0–1，越大越不确定）、exam_weight、learning_gain、learning_minutes 和 prerequisites。置信信息不能直接当作真实掌握概率；可保守地将诊断区间宽度作为 uncertainty。输入缺失的前置知识和循环图会被拒绝。

## 优先级与任务

```text
weakness = 0.8*(1-mastery) + 0.2*(1-平均练习得分率)
priority = (weakness+0.25*uncertainty) * exam_weight * learning_gain
           * (1+0.2*直接后继数) * (1+目标分差比例+0.1*历史考试薄弱度)
           / learning_minutes
```

缺少练习记录时用 mastery 作为低权重回退。历史数据不用于把一次失败直接改成低掌握概率。只有依赖已安排完或满足 mastery≥0.75 且 uncertainty≤0.25 的知识点才可进入下一层学习；掌握阈值是规划启发式，不是实际能力保证。

生成基础学习块、完成后至少1/3/7天的复习，以及每周阶段测验。每个任务有知识点、内容、预计分钟数、难度、可评价完成标准、开始与截止时间。低完成率减少新增日负荷并使用较短学习块。返回长期分数目标、学习/复习/测验阶段目标、周任务分组和每日任务。阶段可以交错进行，不保证提分或按期掌握。

前置“已排完”仅是日程顺序条件，不等于学生已掌握。执行中应根据测验和实际完成记录重新规划。阶段测验覆盖优先知识点及已学习基础，尚未实现自动组卷。

## 重排与约束

重排提交 previous_run_id、新输入及 reason。保存接口读取真实 LearningTask 状态，保留 completed、in_progress 和锁定任务的 ID、时间及内容；其余旧任务标记 cancelled，旧计划 superseded，新计划版本递增。保留的任务不迁移所属旧计划，以免破坏历史和 TaskAttempt 外键；新计划的完整有效任务集合在 PlanningRun.result.tasks 清单中。

其他计划的活动任务也作为固定占用处理。若它们与新可用时段、考试截止或每日额度冲突，返回409并回滚。数据库保存流程锁定学生行（PostgreSQL），串行化本接口针对同一学生的规划保存。

保存时合并数据库 KnowledgeDependency；遗漏必要前置知识返回422。历史已完成/跳过任务用于完成率，历史 TaskAttempt.result_data.score_rate（0–1，完成时间早于规划开始）补充练习表现。旧 TaskAttempt.score 没有满分定义，不猜测其比例。考试表现及诊断掌握指标通过请求传入；可以使用已有诊断 API 输出组装。

validate 独立检查重叠、分钟数与时间区间一致性、当地每日总量、可用时段、截止日期、受保护任务以及前置学习时长。任何将来大模型生成的候选任务都必须经过此节点；本版采用确定性任务模板。约束失败不会进入保存节点。时间不足时返回 partial 和 unmet，不强行超额安排。

同一请求重试返回已有版本，避免重复写入；反馈后使用最新 previous_run_id 和新的 reason 创建后续版本。不可从 superseded 版本再次分叉。审计快照保留优先级分项、输入证据、未安排内容与调整原因。

数据库迁移 `20261013_0004` 新增 planning_runs；已有 LearningPlan、LearningTask 与 TaskAttempt 继续复用。应用仍是本地开发环境，用户身份认证沿用此前尚未完成的状态。

LangGraph 用法依据官方 StateGraph 文档：https://reference.langchain.com/python/langgraph/graph/state/StateGraph
