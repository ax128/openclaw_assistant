"""
将 MD 格式的技能说明转换为项目使用的 JSON 技能格式。
支持 YAML frontmatter（--- ... ---）与 Markdown 正文段落/列表。
用法: python -m utils.md_skill_to_json [input.md] [output.json]
默认: utils/test.md -> 同目录下 {skill_id}.json
"""
import json
import re
import sys
import os


def _slug(s):
    """将 name 转为 snake_case 技能 id，如 bash-script-helper -> bash_script_helper"""
    if not s:
        return "skill"
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", " ", s)
    s = re.sub(r"-+", "_", s.strip()).strip()
    return re.sub(r"\s+", "_", s).lower() or "skill"


def _parse_frontmatter(text):
    """解析 --- ... --- 中的 YAML 风格键值。"""
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return fm, text
    block = m.group(1)
    body = text[m.end() :].lstrip()
    key = None
    value_lines = []
    for line in block.split("\n"):
        if line.strip() == "":
            if key:
                fm[key] = "\n".join(value_lines).strip()
                key = None
                value_lines = []
            continue
        if re.match(r"^\w[\w-]*\s*:", line):
            if key:
                fm[key] = "\n".join(value_lines).strip()
                value_lines = []
            parts = line.split(":", 1)
            key = parts[0].strip()
            rest = parts[1].strip()
            if rest.startswith("|"):
                value_lines = []
            elif rest:
                value_lines = [rest]
            else:
                value_lines = []
        else:
            if key:
                value_lines.append(line)
    if key:
        fm[key] = "\n".join(value_lines).strip()
    return fm, body


def _parse_sections(body):
    """按 ## 标题切分正文，返回 { "Section Title": "content..." }。"""
    sections = {}
    current = None
    lines = []
    for line in body.split("\n"):
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            current = line[3:].strip()
            lines = []
        else:
            if current is not None:
                lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    return sections


def _extract_keywords(description, sections):
    """从 description 与 Example Triggers 等段落提取关键词列表。"""
    keywords = []
    # 从 description 中 "Mention \"...\" in your request" 提取
    for m in re.finditer(r'[Mm]ention\s+"([^"]+)"', description or ""):
        keywords.append(m.group(1).strip())
    # Example Triggers 的列表项（- "xxx"）
    triggers = sections.get("Example Triggers") or sections.get("Example triggers") or ""
    for m in re.finditer(r'-\s*"([^"]+)"', triggers):
        keywords.append(m.group(1).strip())
    for line in (triggers or "").split("\n"):
        line = line.strip()
        if line.startswith("- ") and not line.startswith('- "'):
            t = line[2:].strip().strip('"')
            if t and t not in keywords:
                keywords.append(t)
    return list(dict.fromkeys(kw for kw in keywords if kw))


def md_skill_to_json(md_path, out_path=None):
    """
    读取 MD 文件，转换为技能 JSON（单条技能，符合 pets/skills/*.json 子项格式）。
    out_path 为空时输出到同目录下 {skill_id}.json。
    """
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()
    fm, body = _parse_frontmatter(text)
    sections = _parse_sections(body)
    name = (fm.get("name") or "").strip() or "Unnamed Skill"
    description = (fm.get("description") or "").strip()
    if not description and "Purpose" in sections:
        description = sections["Purpose"].strip()
    skill_id = _slug(name)
    title = name.replace("-", " ").title()
    # 用正文组装 prompt
    purpose = sections.get("Purpose", "").strip()
    when = sections.get("When to Use", "").strip()
    caps = sections.get("Capabilities", "").strip()
    prompt_parts = []
    if purpose:
        prompt_parts.append(f"【目的】{purpose}")
    if when:
        prompt_parts.append(f"【适用场景】{when}")
    if caps:
        prompt_parts.append(f"【能力】{caps}")
    prompt = "\n".join(prompt_parts) if prompt_parts else f"根据技能「{title}」的说明响应用户请求。"
    prompt = f"【任务】{prompt}\n【要求】语气友好、简洁，直接输出回复内容，50–200 字；不要重复用户问题或加「好的」等前缀。"
    keywords = _extract_keywords(description, sections)
    if not keywords:
        # 用 title 拆词或 name 作为默认
        keywords = [title, name]
    skill = {
        "name": title,
        "description": description or f"用户提到「{title}」或相关请求时触发。",
        "call_method": skill_id,
        "enabled": True,
        "prompt": prompt,
        "keywords": keywords[:20],
        "call_function": False,
        "function_name": "",
        "function_params": {},
        "return_result": None,
    }
    out = out_path or os.path.join(os.path.dirname(md_path), f"{skill_id}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({skill_id: skill}, f, indent=2, ensure_ascii=False)
    return out, {skill_id: skill}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    default_md = os.path.join(os.path.dirname(__file__), "test.md")
    default_out = os.path.join(os.path.dirname(__file__), "bash_script_helper.json")
    md_path = sys.argv[1] if len(sys.argv) > 1 else default_md
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.isfile(md_path):
        print(f"文件不存在: {md_path}")
        sys.exit(1)
    out_file, data = md_skill_to_json(md_path, out_path)
    print(f"已生成: {out_file}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
