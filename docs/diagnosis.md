# 数学成绩诊断 Agent

首版是确定性的统计 Agent，无需大模型密钥。编排过程为输入校验 → 逐题失分 → 分数及证据分摊 → 历史估计 → 持续薄弱判定 → 解释报告 → 原子保存。

## API

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | /api/v1/diagnoses/preview | 接收 student_id、current 和 history，返回报告，不写数据库 |
| POST | /api/v1/diagnoses/from-exam | 接收 student_id、exam_id、可选 reasons，读取数据库并保存诊断和掌握度快照 |
| GET | /api/v1/diagnoses/{id} | 查询报告、模型版本及完整输入快照 |

`current` 和 `history` 每个考试包含 `exam_id`、`exam_date`、`total_score`（实际得分）、`max_score`（满分）、`questions`。每题包含 `question_id`、`score`、`max_score`、`difficulty`（0最易、1最难）、`tags`（knowledge_point_id、weight）和可选 `reasons`。

原因分类为 calculation、concept、method、time、unknown。每项原因须包含 `lost_score`、`evidence` 和 `source`（teacher/student/rubric）。原因分数必须互斥，合计不超过该题失分，剩余失分自动归为未知；这是基于提交记录的归因，并非从分数猜测的原因。没有概念/时间归因记录时零分表示“没有已记录归因”，不意味着排除了这些原因。

持久化调用示例：

```json
{"student_id":"实际学生UUID","exam_id":"已完成考试UUID","reasons":{}}
```

`reasons` 可按题目 UUID 映射到原因数组。只允许引用本次考试题目。考试必须属于指定学生且已完成；读取所有早于本次考试的已完成历史，历史同标题同日期只取最高完成版本。首版最多100次历史，超限明确报错。缺失评分不当作零分，总分与各题合计不一致时报422。同日考试不作为历史；预览输入需显式提供完整且无重复的考试集合。

## 统计规则

设得分比例为 r、难度为 d、标签归一化权重为 w、距离本次考试天数为 t。每个知识点使用 Beta(2,2) 伪计数先验：

```text
decay = 2^(-t/180)
alpha = 2 + Σ w × decay × r × (0.5+d)
beta  = 2 + Σ w × decay × (1-r) × (1.5-d)
mastery_index = alpha/(alpha+beta)
effective_evidence = alpha+beta-4
confidence = effective_evidence/(effective_evidence+4)
variance = alpha×beta / ((alpha+beta)^2 × (alpha+beta+1))
interval_95 = [index-sqrt(variance/0.05), index+sqrt(variance/0.05)] ∩ [0,1]
```

标签权重同时用于得分、满分、失分和证据；一道题不会在多个知识点里完整重复计数。分数与难度不等同于独立试验；先验和衰减使单次正确率不会直接变成掌握概率。难题成功相对增加成功证据，难题失败相对减少失败证据，系数为尚未校准的透明启发式。

区间用 Chebyshev 不等式给出伪后验下至少95%质量的保守边界，少量数据时可能为[0,1]。不是实际能力的频率学置信区间，confidence 也不是结论正确概率。报告保存 alpha、beta、标准差、区间和有效证据，支持复核。相关题目或重复试题仍可能高估信息量，后续教育测量模型需要处理这些影响。

持续薄弱：最近一年内最后三次覆盖该知识点的考试，各自分摊后得分率均低于60%，且每次标签权重之和至少1道等效题。未达到判据表示证据不支持持续薄弱，不等于已掌握。当前未覆盖的知识点仍报告历史估计，并明确说明。

`services/diagnosis.py` 中 `MeasurementModel` Protocol 接收得分比例、难度及衰减后权重并返回 `MasteryEstimate`，是后续 IRT/BKT 适配入口；模型版本必须随估计算法更新。目前尚未实现 IRT/BKT。

## 数据与迁移

运行 `alembic upgrade head`，新增 `diagnosis_runs` 保存输入快照、模型版本、报告及不确定性。模型估计写入现有 `StudentKnowledgeState`，source_type=diagnosis，source_id 指向诊断报告。快照中的 evidence_count 是相关题目数；有效分数证据量以报告的 evidence_strength 为准。

同一输入内容及模型版本由数据库唯一约束保证幂等；修正成绩后生成新报告和新快照，旧报告保留。每次从原始考试重算，不把历史快照再作为历史证据重复累加。recorded_at 表示运行时间，考试观测日期保存在 input_snapshot；查询较晚考试的画像时应按报告考试日期选择，不能把补做的旧考试诊断当成最新考试表现。

仍沿用项目的本地开发 API 访问方式，尚未建立用户登录与教师角色权限。

## 运行与验证

```powershell
cd backend
.\.venv\Scripts\python.exe examples/diagnose_exam.py
.\.venv\Scripts\python.exe -m pytest -q
```

示例在本地直接调用同一个诊断服务，输出完整 JSON，不写入真实学生记录，也不需要启动数据库。它使用明确标注的合成记录。对应可读报告见 `docs/example-diagnosis-report.md`。API 请求结构也可在 `/docs` 查看。
