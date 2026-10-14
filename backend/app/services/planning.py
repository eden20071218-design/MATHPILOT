from collections import defaultdict
from datetime import timedelta
from typing import TypedDict
from zoneinfo import ZoneInfo

from langgraph.graph import StateGraph, START, END
from app.schemas.planning import PlanningRequest, PlannedTask
from app.services.deepseek_planning import suggest


class PlanningConflict(ValueError):
    pass


class State(TypedDict, total=False):
    request: PlanningRequest
    priorities: dict
    tasks: list
    unmet: list
    reasons: list
    result: dict
    ai_suggestions: dict
    ai_info: dict


def protected(task):
    return task.status in ('completed', 'in_progress') or (task.locked and task.status not in ('cancelled', 'skipped'))


def diagnosis(state):
    request = state['request']
    reasons = [request.reason, f'当前成绩{request.current_score}/{request.full_score}，目标{request.target_score}；不承诺预测提分。']
    if request.completion_rate < 0.7:
        reasons.append('历史完成率偏低，增加任务分块并降低每日新增负荷。')
    if request.exam_rates:
        reasons.append(f'历史考试平均得分率{sum(request.exam_rates)/len(request.exam_rates):.1%}，作为低权重需求信号。')
    return {'reasons': reasons}


def prioritize(state):
    request = state['request']
    nodes = {k.id: k for k in request.knowledge}
    visiting, visited = set(), set()
    def visit(key):
        if key in visiting:
            raise PlanningConflict('前置知识依赖存在环')
        if key in visited:
            return
        visiting.add(key)
        for pre in nodes[key].prerequisites:
            visit(pre)
        visiting.remove(key)
        visited.add(key)
    for key in nodes:
        visit(key)
    scores = {}
    for key, k in nodes.items():
        practice = sum(k.practice_rates)/len(k.practice_rates) if k.practice_rates else k.mastery
        weakness = 0.8*(1-k.mastery) + 0.2*(1-practice)
        dependents = sum(key in n.prerequisites for n in nodes.values())
        gap = max(0, request.target_score-request.current_score)/request.full_score
        historical_need = 1 - sum(request.exam_rates)/len(request.exam_rates) if request.exam_rates else 0
        score = (weakness+0.25*k.uncertainty)*k.exam_weight*k.learning_gain*(1+0.2*dependents)*(1+gap+0.1*historical_need)/k.learning_minutes
        scores[str(key)] = {'score': score, 'weakness': weakness, 'uncertainty': k.uncertainty,
                            'exam_weight': k.exam_weight, 'gain': k.learning_gain,
                            'dependents': dependents, 'minutes': k.learning_minutes}
    return {'priorities': scores}


def generate(state):
    request = state['request']
    zone = ZoneInfo(request.timezone)
    tasks = [t.model_copy(deep=True) for t in request.existing_tasks if protected(t)]
    unmet = []
    nodes = {k.id: k for k in request.knowledge}
    finished = {}
    for k in request.knowledge:
        if k.mastery >= 0.75 and k.uncertainty <= 0.25:
            finished[k.id] = request.start_at
    reserved_minutes = defaultdict(int)
    reserved_end = {}
    for task in tasks:
        if task.kind == 'learn':
            reserved_minutes[task.knowledge_point_id] += task.minutes
            reserved_end[task.knowledge_point_id] = max(reserved_end.get(task.knowledge_point_id, task.end), task.end)
    for key, minutes in reserved_minutes.items():
        if key in nodes and minutes >= nodes[key].learning_minutes:
            finished[key] = reserved_end[key]
    windows = sorted(request.availability, key=lambda w: w.start)
    new_budget = max(10, int(request.daily_minutes * (0.6+0.4*request.completion_rate))) if request.daily_minutes else 0

    def place(k, kind, minutes, earliest, text, criterion):
        for window in windows:
            start = max(window.start, request.start_at, earliest)
            day = start.astimezone(zone).date()
            used = sum(t.minutes for t in tasks if t.start.astimezone(zone).date() == day)
            if used + minutes > min(new_budget, request.daily_minutes):
                continue
            occupied = sorted((t for t in tasks if t.start < window.end and t.end > start), key=lambda t: t.start)
            for block in occupied:
                if start + timedelta(minutes=minutes) <= block.start:
                    break
                start = max(start, block.end)
            end = start + timedelta(minutes=minutes)
            if end <= min(window.end, request.exam_at):
                task = PlannedTask(knowledge_point_id=k.id, kind=kind, content=text, minutes=minutes,
                    difficulty=min(0.8, max(0.2, k.mastery+0.1)), completion_criterion=criterion, start=start, end=end)
                tasks.append(task)
                return task
        return None

    pending = set(nodes) - set(finished)
    while pending:
        ready = [key for key in pending if all(p in finished for p in nodes[key].prerequisites)]
        if not ready:
            unmet.extend(f'{nodes[key].name}：前置学习未能安排' for key in sorted(pending, key=str))
            break
        key = max(ready, key=lambda key: (state['priorities'][str(key)]['score'], str(key)))
        k = nodes[key]
        earliest = max([request.start_at, reserved_end.get(key, request.start_at), *[finished[p] for p in k.prerequisites]])
        remaining = k.learning_minutes - reserved_minutes[key]
        last = None
        while remaining:
            minutes = min(remaining, request.daily_minutes, new_budget, 20 if request.completion_rate < 0.7 else 30)
            if minutes <= 0:
                break
            advice = state.get('ai_suggestions', {}).get(k.id)
            task = place(k, 'learn', minutes, earliest,
                         advice.content if advice else f'学习{k.name}：复述定义、整理适用条件并完成分步例题',
                         advice.completion_criterion if advice else '提交定义与条件清单、至少2道带过程的基础题；记录未理解步骤，完成后复测')
            if task is None:
                break
            remaining -= minutes
            earliest = task.end
            last = task
        pending.remove(key)
        if remaining:
            unmet.append(f'{k.name}：尚缺{remaining}分钟基础学习，时间不足')
        elif last:
            finished[key] = last.end
    # Reviews follow foundation scheduling so they cannot consume prerequisite capacity first.
    for key, end in sorted(finished.items(), key=lambda pair: str(pair[0])):
        if key not in nodes:
            continue
        k = nodes[key]
        for days in (1, 3, 7):
            earliest = max(end, request.start_at) + timedelta(days=days)
            if earliest >= request.exam_at:
                continue
            if not place(k, 'review', 10, earliest, f'间隔复习{k.name}（至少间隔{days}天）', '闭卷完成2题并订正，记录正确率和错误原因'):
                unmet.append(f'{k.name}：第{days}天复习未安排，额度不足')
    checkpoint = request.start_at + timedelta(days=6)
    while checkpoint < request.exam_at:
        eligible = [nodes[k] for k, end in finished.items() if k in nodes and end <= checkpoint]
        if eligible:
            k = max(eligible, key=lambda k: state['priorities'][str(k.id)]['score'])
            if not place(k, 'assessment', 20, checkpoint, f'阶段测验：{k.name}及已学习基础', '限时完成4题；提交得分、用时、错误类型，据此重新规划'):
                unmet.append(f'{checkpoint.date()}阶段测验：时间不足')
        checkpoint += timedelta(days=7)
    return {'tasks': sorted(tasks, key=lambda t: (t.start, str(t.id))), 'unmet': unmet}


def validate(state):
    request, tasks = state['request'], state['tasks']
    zone = ZoneInfo(request.timezone)
    totals = defaultdict(int)
    prior = None
    original = {t.id: t for t in request.existing_tasks if protected(t)}
    for task in sorted(tasks, key=lambda t: t.start):
        if task.id in original and task != original[task.id]:
            raise PlanningConflict('受保护任务被修改')
        if task.end <= task.start or (task.end-task.start).total_seconds() != task.minutes*60:
            raise PlanningConflict('任务时长与时间区间不一致')
        if task.start.astimezone(zone).date() != task.end.astimezone(zone).date():
            raise PlanningConflict('任务跨越当地日期')
        if prior is not None and task.start < prior.end:
            raise PlanningConflict('任务时间冲突；请调整受保护任务或可用时段')
        prior = task
        if task.status == 'completed' and task.end <= request.start_at:
            continue
        if task.end > request.exam_at:
            raise PlanningConflict('任务超出考试期限')
        if task.id not in original and task.start < request.start_at:
            raise PlanningConflict('新增任务早于规划开始')
        if not any(w.start <= task.start and task.end <= w.end for w in request.availability):
            raise PlanningConflict('受保护任务不在可用时段内，无法安全重排')
        totals[task.start.astimezone(zone).date()] += task.minutes
    if any(n > request.daily_minutes for n in totals.values()):
        raise PlanningConflict('每日学习额度超限')
    if not set(original) <= {t.id for t in tasks}:
        raise PlanningConflict('受保护任务丢失')
    # Independently recheck foundation ordering, including fixed user tasks.
    nodes = {k.id: k for k in request.knowledge}
    for task in tasks:
        if task.status == 'completed' or task.knowledge_point_id not in nodes:
            continue
        for pre in nodes[task.knowledge_point_id].prerequisites:
            k = nodes[pre]
            if k.mastery >= 0.75 and k.uncertainty <= 0.25:
                continue
            prior_minutes = sum(t.minutes for t in tasks if t.knowledge_point_id == pre and t.kind == 'learn' and t.end <= task.start)
            if prior_minutes < k.learning_minutes:
                raise PlanningConflict('任务未满足前置知识学习时长')
    weeks = defaultdict(list)
    for t in tasks:
        if t.end <= request.start_at:
            continue
        week = max(1, (t.start.astimezone(zone).date()-request.start_at.astimezone(zone).date()).days//7+1)
        weeks[week].append(str(t.id))
    weekly = [{'week': week, 'goal': '完成基础学习并通过阶段小测，依据反馈检查目标差距', 'task_ids': ids}
              for week, ids in sorted(weeks.items())]
    stages = []
    for kind, goal in [('learn', '补齐必要前置知识与薄弱知识的基础题'), ('review', '间隔提取记忆并订正错题'),
                       ('assessment', '阶段测验验证学习结果并触发反馈重排')]:
        selected = [t for t in tasks if t.kind == kind and t.end > request.start_at]
        if selected:
            stages.append({'stage': kind, 'goal': goal, 'start': min(t.start for t in selected).isoformat(),
                           'deadline': max(t.end for t in selected).isoformat(), 'task_ids': [str(t.id) for t in selected]})
    reasons = [*state['reasons'], f'保留{len(original)}个已完成、进行中或锁定任务；按最新证据重建其余日程。']
    ai_info = state.get('ai_info', {'status': 'not_requested'})
    if ai_info['status'] == 'used':
        reasons.append('DeepSeek 仅提供学习任务文案建议；优先级、时间和前置依赖仍由确定性规则计算与校验。')
    elif ai_info['status'] in ('fallback', 'not_configured'):
        reasons.append('AI 建议不可用，已使用确定性任务模板。')
    return {'result': {'model_version': 'planner-v1', 'tasks': [t.model_dump(mode='json') for t in tasks],
        'priorities': state['priorities'], 'stages': stages, 'weekly_plans': weekly,
        'long_term_goal': {'current_score': request.current_score, 'target_score': request.target_score, 'exam_at': request.exam_at.isoformat()},
        'daily_minutes': {str(day): minutes for day, minutes in sorted(totals.items())},
        'unmet': state['unmet'], 'adjustment_reasons': reasons,
        'status': 'partial' if state['unmet'] else 'scheduled', 'ai': ai_info}}


def build_workflow(save=None, ai_api_key=None):
    graph = StateGraph(State)
    for name, function in [('diagnosis', diagnosis), ('priority', prioritize),
                           ('ai_suggest', lambda state: suggest(state, api_key=ai_api_key)),
                           ('generate', generate), ('validate', validate),
                           ('save', save or (lambda state: {}))]:
        graph.add_node(name, function)
    chain = [START, 'diagnosis', 'priority', 'ai_suggest', 'generate', 'validate', 'save', END]
    for before, after in zip(chain, chain[1:]):
        graph.add_edge(before, after)
    return graph.compile()


def plan(request: PlanningRequest, ai_api_key=None):
    return build_workflow(ai_api_key=ai_api_key).invoke({'request': request})['result']
