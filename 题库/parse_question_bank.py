#!/usr/bin/env python3
"""
把"机械设计基础A2（26-27-1）(题库部分导出).doc"解析成结构化JSON。

这个.doc其实不是老版二进制Word格式的真实内容——用olefile打开它唯一的
WordDocument流，读出来是一份UTF-8编码的HTML（超星系统"导出题库"功能生成的
套壳文件，Word能打开是因为Word会自动识别HTML内容，跟扩展名无关）。

输出两个文件：
  题库.json          —— 全部题目，按设计好的schema（见 提示词库.md 或本文件顶部说明）
  知识点聚类预览.md   —— 用jieba分词做的粗聚类结果，每组附题数+示例题干，供人工核对/命名

运行： python3 parse_question_bank.py
"""

import base64
import json
import os
import re
import sys
from collections import Counter, defaultdict

import olefile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.join(BASE_DIR, "..", "测试外部agent服务")
sys.path.insert(0, AGENT_DIR)
from knowledge_base import classify_knowledge_point  # noqa: E402  (与实时agent共用同一套分类逻辑，见该文件顶部说明)
DOC_PATH = os.path.join(BASE_DIR, "机械设计基础A2（26-27-1）(题库部分导出).doc")
IMAGES_DIR = os.path.join(BASE_DIR, "images")
OUTPUT_JSON = os.path.join(BASE_DIR, "题库.json")
OUTPUT_CLUSTER_REPORT = os.path.join(BASE_DIR, "知识点聚类预览.md")

TYPE_MAP = {
    "单选题": "single_choice",
    "多选题": "multiple_choice",
    "判断题": "true_false",
    "填空题": "fill_blank",
    "简答题": "short_answer",
    "分录题": "fill_blank",  # 源系统标签bug，内容结构等同填空题
}

SOURCE_LABEL = "机械设计基础A2 26-27-1 题库导出"


def load_html():
    ole = olefile.OleFileIO(DOC_PATH)
    data = ole.openstream("WordDocument").read()
    return data.decode("utf-8", errors="replace")


def strip_tags(html_fragment: str) -> str:
    """去HTML标签取纯文本，&nbsp;等实体做基本还原，多余空白折叠。"""
    text = re.sub(r"<br\s*/?>", "\n", html_fragment)
    text = re.sub(r"<[^>]+>", "", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def extract_images(html_fragment: str, seq: int) -> list:
    """题干里的图：base64的存成本地文件，外链的直接记URL。"""
    images = []
    # base64内嵌图
    for i, m in enumerate(re.finditer(r'<img[^>]*src="data:image/(\w+);base64,([^"]+)"[^>]*>', html_fragment)):
        ext, b64data = m.group(1), m.group(2)
        fname = f"q{seq}_{i}.{ext}"
        fpath = os.path.join(IMAGES_DIR, fname)
        try:
            with open(fpath, "wb") as f:
                f.write(base64.b64decode(b64data))
            images.append({"type": "local_file", "value": f"images/{fname}"})
        except Exception as e:
            images.append({"type": "error", "value": f"base64解码失败: {e}"})
    # 外链图（超星CDN等），排除已经当base64处理过的img标签
    for m in re.finditer(r'<img[^>]*src="(https?://[^"]+)"[^>]*>', html_fragment):
        # 原始HTML里查询参数的&被转义成了&amp;，不反转义会导致重定向地址里多出字面的"amp;"
        url = m.group(1).replace("&amp;", "&")
        images.append({"type": "url", "value": url})
    return images


def parse_stem_and_type(block: str):
    """从形如 <p><strong>77、题干...</strong></p> ... <strong> (填空题) </strong> 里
    抠出题干HTML片段和题型中文标签。"""
    stem_match = re.search(r"<p[^>]*><strong>\d+、(.*?)</strong></p>", block, re.DOTALL)
    stem_html = stem_match.group(1) if stem_match else ""
    type_match = re.search(r"\((单选题|多选题|判断题|填空题|简答题|分录题)\)", block)
    type_cn = type_match.group(1) if type_match else None
    return stem_html, type_cn


def parse_options(block: str) -> list:
    options = []
    for m in re.finditer(r"<span>([A-Z])、</span>\s*<span>(.*?)</span>", block, re.DOTALL):
        label, text_html = m.group(1), m.group(2)
        options.append({"label": label, "text": strip_tags(text_html)})
    return options


def parse_answer(block: str, type_en: str):
    m = re.search(r"答案：</span>\s*<span>(.*?)</span>\s*(?:<br>|$)", block, re.DOTALL)
    raw = strip_tags(m.group(1)) if m else ""

    if type_en == "true_false":
        if "正确" in raw:
            return True
        if "错误" in raw:
            return False
        return None
    if type_en == "multiple_choice":
        # 形如 "ABC" -> ["A","B","C"]；也兼容已经有分隔符的情况
        letters = re.findall(r"[A-Z]", raw)
        return letters if letters else []
    if type_en == "fill_blank":
        # 形如 "<p>6</p>； <p>3</p>； <p>3</p>；" -> 抠每个<p>里的值
        parts = re.findall(r"<p>(.*?)</p>", m.group(1), re.DOTALL) if m else []
        if parts:
            return [strip_tags(p) for p in parts if strip_tags(p)]
        # 没有<p>包裹的单空情况，按中文分号/顿号切
        cleaned = [s.strip() for s in re.split(r"[；;]", raw) if s.strip()]
        return cleaned if cleaned else ([raw] if raw else [])
    if type_en == "single_choice":
        letters = re.findall(r"[A-Z]", raw)
        return letters[0] if letters else raw
    # short_answer 等：原样返回文本（很多时候是空字符串）
    return raw


def parse_explanation(block: str) -> str:
    m = re.search(r"解析：</span>\s*(.*?)\s*(?:<br>|$)", block, re.DOTALL)
    if not m:
        return ""
    return strip_tags(m.group(1))


def parse_difficulty(block: str) -> str:
    m = re.search(r"难易度：\s*</span>\s*<span>\s*(易|中|难)\s*</span>", block)
    if m:
        return m.group(1)
    m = re.search(r"难易度：\s*([易中难])", block)
    return m.group(1) if m else ""


def parse_all_questions():
    html = load_html()
    blocks = re.split(r"(?=<p[^>]*><strong>\d+、)", html)
    questions = []
    skipped = 0
    for block in blocks:
        num_match = re.match(r"<p[^>]*><strong>(\d+)、", block)
        if not num_match:
            continue
        seq = int(num_match.group(1))
        stem_html, type_cn = parse_stem_and_type(block)
        if type_cn is None:
            skipped += 1
            continue
        type_en = TYPE_MAP[type_cn]

        question = {
            "id": f"q_{seq:04d}",
            "seq": seq,
            "type": type_en,
            "stem": strip_tags(stem_html),
            "stem_images": extract_images(block[:block.find("答案：") if "答案：" in block else len(block)], seq),
            "options": parse_options(block) if type_en in ("single_choice", "multiple_choice") else [],
            "answer": parse_answer(block, type_en),
            "explanation": parse_explanation(block),
            "difficulty": parse_difficulty(block),
            "knowledge_point_id": None,
            "source": SOURCE_LABEL,
        }
        questions.append(question)
    return questions, skipped


# ----------------------------------------------------------------------
# 知识点打标：直接复用 测试外部agent服务/knowledge_base.py 的 classify_knowledge_point()，
# 不再自己维护一份关键词表——保证"agent实时问答认的知识点"和"题库打的标签"是同一套体系。
# ----------------------------------------------------------------------

def tag_with_knowledge_points(questions: list) -> dict:
    """给每道题按stem分类，返回 {knowledge_point_id_or_None: [questions]} 分组，
    供写JSON时回填 knowledge_point_id，以及生成人工核对用的聚类报告。"""
    groups = defaultdict(list)
    for q in questions:
        kp = classify_knowledge_point(q["stem"])
        q["knowledge_point_id"] = kp.id if kp else None
        groups[kp.id if kp else "【待人工归类】"].append(q)
    return groups


def write_cluster_report(groups: dict):
    lines = ["# 知识点分类结果预览（复用knowledge_base.py的分类逻辑）\n"]
    lines.append(f"总题数：{sum(len(v) for v in groups.values())}，知识点分组数：{len(groups)}\n")
    for term, qs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"\n## {term}（{len(qs)}题）\n")
        for q in qs[:3]:
            stem_preview = q["stem"][:60].replace("\n", " ")
            lines.append(f"- [{q['id']}] ({q['type']}) {stem_preview}...")
    with open(OUTPUT_CLUSTER_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    questions, skipped = parse_all_questions()
    print(f"解析完成：{len(questions)} 题，跳过 {skipped} 个无法识别题型的片段")

    groups = tag_with_knowledge_points(questions)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    print(f"已写入 {OUTPUT_JSON}")

    write_cluster_report(groups)
    print(f"已写入 {OUTPUT_CLUSTER_REPORT}（{len(groups)} 个知识点分组，含'待人工归类'）")

    # 简单校验：按题型统计 + 抽查answer为空的比例，方便发现解析bug
    type_counter = Counter(q["type"] for q in questions)
    print("题型分布：", dict(type_counter))
    empty_answer = sum(1 for q in questions if not q["answer"] and q["answer"] != False)
    print(f"answer为空的题目数：{empty_answer}（简答题/部分填空题源数据本身可能就没给答案，属正常现象）")


if __name__ == "__main__":
    main()
