"""Import documented GitHub search results without promoting unreviewed records.

Input: {repositories: {key: {repository: REST search item, category, query,
source, fetched_at}}, searches: [{query, page, total_count, ...}]}.
"""
import argparse
import json
import re
from pathlib import Path

import yaml
from catalog import ROOT, load_catalog, load_metrics, validate, write_json
from fetch_metrics import normalize

USES = {
    "ai-education": "可评估用于教学资料知识库、课程问答或学习助手；具体能力待核对。",
    "courseware": "可评估用于课件、教学白板或课堂演示内容制作；具体能力待核对。",
    "simulation": "可评估用于数学、物理或 STEM 计算实验和可视化教学；具体能力待核对。",
    "programming": "可评估用于编程教学、示例练习或 STEM 学习；具体能力待核对。",
    "courses": "可评估作为课程、教材、教程或自主学习参考；具体内容待核对。",
    "learning-platforms": "可评估用于课程管理、学习活动或线上培训平台；具体能力待核对。",
    "assessment": "可评估用于测验、练习、考试或编程评测；具体能力待核对。",
    "self-learning": "可评估用于学习笔记、知识整理、闪卡或复习；具体能力待核对。",
    "school-management": "可评估用于学校教务、学生或培训机构管理；具体能力待核对。",
    "language-learning": "可评估用于外语词汇、阅读或语言练习；具体能力待核对。",
    "collaboration": "可评估用于在线课堂、教学团队协作或学习小组；具体能力待核对。",
    "documents": "可评估用于教材文档处理、PDF 编辑或文字识别；具体能力待核对。",
    "media-tools": "可评估用于课程录制、字幕、音视频或课堂转写；具体能力待核对。",
}


def classify(repo, category):
    text = ((repo.get("description") or "") + " " + repo["name"]).lower()
    topics = set(repo.get("topics", []))
    if category == "programming":
        for target, signals in (
            ("school-management", {"school-management", "student-management"}),
            ("learning-platforms", {"lms", "learning-management-system", "e-learning", "mooc"}),
            ("assessment", {"online-judge", "quiz", "exam", "quiz-app"}),
            ("language-learning", {"language-learning", "english-learning"}),
            ("self-learning", {"anki", "flashcards", "spaced-repetition", "note-taking"}),
            ("courseware", {"whiteboard", "presentation", "slides", "manim"}),
        ):
            if topics & signals:
                category = target
                break
    resource = bool(re.search(r"\b(book|books|tutorial|tutorials|curriculum|course|courses|roadmap|guide|resources|collection|curated|awesome|lessons)\b|教材|教程|课程|学习路线|资源|指南", text))
    application = bool(re.search(r"\b(app|platform|editor|server|framework|library|toolkit|engine|api|sdk|system)\b|平台|编辑器|系统", text))
    kind = "resource" if resource and not application else "application"
    if kind == "resource" and category == "programming":
        category = "courses"
    if kind == "application" and re.search(r"\b(library|framework|sdk|toolkit)\b", text):
        kind = "library"
    native = kind == "resource" or category in {"learning-platforms", "assessment", "school-management", "language-learning"}
    native = native or bool(re.search(r"\b(educational|education|teaching|tutor|flashcard|flashcards|learning platform)\b|教学|教育|背单词", text))
    return category, kind, "native" if native else "adaptable"


def import_results(raw, root=ROOT):
    config, projects = load_catalog(root)
    metrics = load_metrics(root)
    existing = {p["github"].lower() for p in projects}
    canonical_ids = {m["repository_id"] for m in metrics["repositories"].values() if m.get("repository_id")}
    ids = {c["id"] for c in config["categories"]}
    count = 0
    skipped = []
    for key, entry in sorted(raw["repositories"].items()):
        repo = entry["repository"]
        key = repo["full_name"].lower()
        if key in existing:
            metrics["repositories"][key] = normalize(repo, entry["fetched_at"])
            continue
        # Hiring lists and domain-registration services are outside the learning catalog.
        if key in {"poteto/hiring-without-whiteboards", "digitalplatdev/freedomain"}:
            skipped.append({"github": repo["full_name"], "reason": "检索标签命中，但主要内容为招聘列表或域名注册服务。"})
            continue
        if repo.get("archived") or repo.get("disabled") or repo.get("fork") or repo["id"] in canonical_ids:
            continue
        category, kind, relation = classify(repo, entry["category"])
        if category not in ids:
            raise ValueError("Unknown category " + category)
        description = repo.get("description") or ""
        p = {
            "schema_version": 1, "name": repo["name"], "github": repo["full_name"],
            "description_zh": "通过教育相关主题检索收集；" + USES[category],
            "upstream_description": description, "category": category, "kind": kind,
            "tags": repo.get("topics", []) or [category], "education_relation": relation,
            "audience": ["教师", "学习者", "教育产品开发者"], "education_use": USES[category],
            "cost": "未逐项核对费用与托管条件，见上游说明。",
            "deployment": "未逐项部署；资源、应用和开发组件按上游 README 使用。",
            "license_note": "仅收集 API 许可证标识，课程、模型和附属资产条款待核对。",
            "status": "discovered",
            "discovery": {"query": entry["query"], "topics": repo.get("topics", [])},
            "review": {"level": "metadata_collected", "checked_at": entry["fetched_at"],
                       "method": "GitHub 搜索 API 元数据收集与规则分类；未逐项阅读 README、运行或验证教学效果。分类和教育关系待资料核对。",
                       "sources": ["https://github.com/" + repo["full_name"], entry["source"]]},
        }
        metrics["repositories"][key] = normalize(repo, entry["fetched_at"])
        errors = validate(config, [dict(p, _file=key.replace("/", "--") + ".yml")], metrics)
        if errors:
            raise ValueError("\n".join(errors))
        (root / "data/projects" / (key.replace("/", "--") + ".yml")).write_text(yaml.safe_dump(p, allow_unicode=True, sort_keys=False), encoding="utf-8")
        canonical_ids.add(repo["id"])
        count += 1
    stamp = max(e["fetched_at"] for e in raw["repositories"].values())
    metrics["last_attempt_at"] = stamp
    write_json(root / "data/metrics.json", metrics)
    write_json(root / "data/snapshots" / (stamp[:10] + ".json"), metrics)
    write_json(root / "data/discovery.json", {"schema_version": 1, "collected_at": stamp, "input_unique_count": len(raw["repositories"]), "new_count": count, "skipped": skipped, "searches": raw["searches"]})
    print("Imported {} new documented repositories.".format(count))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入有检索来源的 GitHub 搜索结果，默认保持元数据收集状态")
    parser.add_argument("input", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    import_results(json.loads(args.input.read_text(encoding="utf-8")), args.root)
