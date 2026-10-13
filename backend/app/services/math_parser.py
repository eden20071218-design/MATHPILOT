"""Conservative local parser. Confidence measures extraction, NOT mathematical truth."""
import re
import unicodedata

from app.schemas.knowledge import Example, Formula, KnowledgeContent, ParsedMaterial


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def split_names(value: str) -> list[str]:
    return [item.strip().strip("`$") for item in re.split(r"[,，;；、]", value) if item.strip()]


def assess(point: KnowledgeContent) -> KnowledgeContent:
    reasons = list(point.review_reasons)
    if not point.definition and not point.theorems:
        reasons.append("缺少定义或定理陈述")
    if not point.conditions and (point.theorems or any(not f.conditions for f in point.formulas)):
        reasons.append("公式或定理的适用条件未完整说明")
    if any(word in point.evidence for word in ("可能", "大概", "疑似", "待确认", "?", "？")):
        reasons.append("原文含不确定或有歧义的表述")
    for formula in point.formulas:
        expression = formula.expression
        if expression.count("(") != expression.count(")") or expression.count("{") != expression.count("}"):
            reasons.append("公式括号不匹配，疑似转录错误")
        if re.search(r"/\s*0(?:\D|$)", expression):
            reasons.append("公式含除以零，需核实适用条件")
    reasons.append("尚未经人工数学审核")
    return point.model_copy(update={"review_reasons": list(dict.fromkeys(reasons))})


def parse_text(text: str) -> ParsedMaterial:
    points: list[KnowledgeContent] = []
    current: dict | None = None
    evidence: list[str] = []
    last_field: str | None = None
    warnings: list[str] = []

    def finish():
        if current is not None:
            current["evidence"] = "\n".join(evidence)
            current["confidence"] = 0.8 if current.get("definition") else 0.45
            points.append(assess(KnowledgeContent.model_validate(current)))

    fields = {
        "别名": "aliases", "又称": "aliases", "定义": "definition", "定理": "theorems",
        "公式": "formulas", "条件": "conditions", "适用条件": "conditions",
        "题型": "question_types", "相关题型": "question_types", "方法": "methods",
        "解题方法": "methods", "前置": "prerequisites", "前置知识": "prerequisites",
        "前置依赖": "prerequisites", "例题": "examples", "答案": "answer",
        "解析": "solution", "解答": "solution", "关联知识点": "knowledge_points",
    }
    for raw in text.replace("\r\n", "\n").splitlines():
        line = raw.strip()
        if not line or line in ("$$", "```", "```markdown", "```text"):
            continue
        heading = re.match(r"^#{1,6}\s+(.+)$", line) or re.match(r"^知识点\s*[:：]\s*(.+)$", line)
        if heading:
            finish()
            name = re.sub(r"^知识点\s*[:：]\s*", "", heading.group(1)).strip()
            current = {"name": name}
            evidence = [raw]
            last_field = None
            continue
        if current is None:
            # Common free-text definition: 极限是…… / 导数指……
            prose = re.match(r"^([^。；：`]{1,30}?)(?:是指|定义为|是)(.+)$", line)
            if prose:
                current = {"name": prose.group(1), "definition": line}
                evidence = [raw]
                last_field = "definition"
                continue
            warnings.append("未识别为知识点的文本：" + line[:80])
            continue
        evidence.append(raw)
        cleaned = re.sub(r"^[-*+]\s+", "", line).replace("**", "")
        match = re.match(r"^([^:：]{1,15})[:：]\s*(.+)$", cleaned)
        if match and match.group(1) in fields:
            field = fields[match.group(1)]
            value = match.group(2).strip()
            last_field = field
            if field == "definition":
                current[field] = (current.get(field, "") + "\n" + value).strip()
            elif field == "formulas":
                current.setdefault(field, []).append(Formula(expression=value.strip("$")))
            elif field == "examples":
                current.setdefault(field, []).append(Example(stem=value))
            elif field in ("answer", "solution", "knowledge_points"):
                if not current.get("examples"):
                    warnings.append("答案或解析没有对应例题")
                else:
                    setattr(current["examples"][-1], field, split_names(value) if field == "knowledge_points" else value)
            elif field in ("aliases", "prerequisites", "question_types"):
                current.setdefault(field, []).extend(split_names(value))
            else:
                current.setdefault(field, []).append(value)
        elif line.startswith("$$") or (line.startswith("$") and line.endswith("$")):
            current.setdefault("formulas", []).append(Formula(expression=line.strip("$")))
        elif last_field == "definition":
            current["definition"] += "\n" + line
        elif last_field in ("solution", "answer") and current.get("examples"):
            example = current["examples"][-1]
            setattr(example, last_field, (getattr(example, last_field) or "") + "\n" + line)
        else:
            current.setdefault("review_reasons", []).append("存在未分类文本，需检查原文")
    finish()
    if not points:
        raise ValueError("未识别知识点；请使用 Markdown 标题、知识点：名称或名称是……的定义文本")
    return ParsedMaterial(knowledge_points=points, warnings=list(dict.fromkeys(warnings)))
