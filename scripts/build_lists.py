"""Generate deterministic Markdown from reviewed records and cached metrics."""
import argparse
import json
import yaml
from datetime import timedelta
from pathlib import Path

from catalog import ROOT, RELATIONS, REVIEW_LEVELS, STAR_TIERS, bucket, catalog_visible, star_tier, load_catalog, load_metrics, local_time, md, parse_time, validate


def previous_snapshot(root, metrics):
    current = metrics.get("last_attempt_at", "")
    snapshots = []
    for path in (root / "data/snapshots").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        stamp = data.get("last_attempt_at", "")
        if stamp and stamp < current:
            snapshots.append((stamp, data))
    return max(snapshots, key=lambda item: item[0]) if snapshots else None


def license_text(metric):
    value = metric.get("license")
    return "需复核" if not value or value == "NOASSERTION" else value


def table(projects, repositories, previous=None):
    lines = ["| 项目 | Star | 教育关系 | 教学用途 | 许可证标识 |", "| --- | ---: | --- | --- | --- |"]
    for p in projects:
        m = repositories.get(p["github"].lower(), {})
        stars = "{:,}".format(m["stars"]) if type(m.get("stars")) is int else "待获取"
        lines.append("| [{}](https://github.com/{}) | {} | {} | {} | {} |".format(
            md(p["name"]), p["github"], stars, RELATIONS[p["education_relation"]], md(p["education_use"]), md(license_text(m))))
    return "\n".join(lines) + "\n"


def state_note(p, m, min_stars):
    group = bucket(p, m, min_stars)
    if group == "retired":
        return p.get("status_reason") or "GitHub 已归档或禁用，移出主清单。"
    if group == "candidates":
        return p.get("status_reason") or "尚无可核验的 Star 数据。"
    if group == "watchlist":
        return "Star 未达到主清单 {} 门槛，保留教育用途记录。".format(min_stars)
    if group == "discovered":
        return "已收集仓库元数据，尚未逐项阅读 README 或验证运行。"
    return "符合当前收录门槛。"


def details(p, m, policy, reference_time, baseline):
    review = p["review"]
    lines = ["### {}".format(md(p["name"])), "", md(p["description_zh"]), "",
             "- 仓库：[{}](https://github.com/{})".format(md(p["github"]), p["github"]),
             "- 教育关系：{}；适用对象：{}。".format(RELATIONS[p["education_relation"]], md("、".join(p["audience"]))),
             "- 教学用途：{}".format(md(p["education_use"])),
             "- 标签：{}".format(md("、".join(p["tags"]))),
             "- 使用成本：{}".format(md(p["cost"])),
             "- 部署：{}".format(md(p["deployment"])),
             "- 许可说明：{}".format(md(p["license_note"])),
             "- 审核：{}（{}，北京时间）；{}".format(REVIEW_LEVELS[review["level"]], local_time(review["checked_at"], date_only=True), md(review["method"])),
             "- 收录状态：{}".format(md(state_note(p, m, policy["min_stars"])))]
    if type(m.get("stars")) is int:
        lines.append("- Star：{:,}；最近推送：{}；数据获取：{}。".format(m["stars"], local_time(m.get("pushed_at")), local_time(m["fetched_at"])))
        if m.get("pushed_at") and reference_time - parse_time(m["pushed_at"]) >= timedelta(days=policy["inactive_days"]):
            lines.append("- 维护提示：超过 {} 天未推送，需复核当前维护状态。".format(policy["inactive_days"]))
        old = (baseline or {}).get("repositories", {}).get(p["github"].lower(), {})
        if type(old.get("stars")) is int:
            lines.append("- 较上一期快照 Star 变化：{:+,}。".format(m["stars"] - old["stars"]))
    if m.get("fetch_status") == "error":
        lines.append("- 更新提示：本次抓取失败；如有历史数据，以上数值及日期保持为上次成功获取结果。")
    if p.get("replacement"):
        lines.append("- 替代仓库：[{}](https://github.com/{})".format(md(p["replacement"]), p["replacement"]))
    lines.append("- 核对来源：" + "、".join("[来源 {}]({})".format(i + 1, url) for i, url in enumerate(review["sources"])))
    return "\n".join(lines) + "\n"


def catalog_table(projects, repositories, titles):
    kinds = {"application": "应用", "resource": "课程／资源", "library": "开发组件"}
    lines = ["| 仓库 | Star | 分类／类型 | 教育关系 | 用途或上游简介 | 核对深度 |", "| --- | ---: | --- | --- | --- | --- |"]
    for p in projects:
        m = repositories[p["github"].lower()]
        description = " ".join((p.get("upstream_description") or p["description_zh"]).split())
        if len(description) > 150:
            description = description[:147] + "…"
        lines.append("| [{}](https://github.com/{}) | {:,} | {}／{} | {} | {} | {} |".format(
            md(p["github"]), p["github"], m["stars"], md(titles[p["category"]]), kinds[p.get("kind", "application")],
            RELATIONS[p["education_relation"]], md(description), REVIEW_LEVELS[p["review"]["level"]]))
    return "\n".join(lines) + "\n"


def render(root=ROOT):
    config, projects = load_catalog(root)
    metrics = load_metrics(root)
    errors = validate(config, projects, metrics)
    if errors:
        raise ValueError("\n".join(errors))
    repositories = metrics["repositories"]
    policy = config["policy"]
    stamp = metrics.get("last_attempt_at")
    reference_time = parse_time(stamp or "1970-01-01T00:00:00Z")
    previous = previous_snapshot(root, metrics)
    baseline = previous[1] if previous else None
    projects.sort(key=lambda p: (-repositories.get(p["github"].lower(), {}).get("stars", -1), p["github"].lower()))
    groups = {name: [] for name in ("main", "watchlist", "candidates", "retired", "discovered")}
    for p in projects:
        groups[bucket(p, repositories.get(p["github"].lower(), {}), policy["min_stars"])].append(p)
    active = [p for p in projects if catalog_visible(p, repositories.get(p["github"].lower(), {}))]
    titles = {c["id"]: c["title"] for c in config["categories"]}
    output = {}
    summary = ["## 清单状态", "", "项目库 **{:,}** 个有效仓库；已核对高星精选 **{}** 个；元数据收集 **{:,}** 个；归档／移出 **{}** 个。".format(len(active), len(groups["main"]), len(groups["discovered"]), len(groups["retired"])), "",
               "数据更新尝试：{}。每个条目的成功获取时间见 YAML 与机器可读索引。".format(local_time(stamp) if stamp else "尚未获取"), "",
               "Star 变化基线：{}。".format(local_time(previous[0]) if previous else "尚无上一期快照，暂不计算增长"), "",
               "## Star 分层", "", "区间下限包含、上限不包含；1K = 1,000，100K = 100,000。数量按有效仓库去重，包含不同核对深度。", "",
               "| 层级 | 项目数 | 浏览 |", "| --- | ---: | --- |"]
    for tier_id, title, lower, upper in STAR_TIERS:
        selected = [p for p in active if star_tier(repositories[p["github"].lower()]["stars"]) == tier_id]
        filename = "lists/tiers/{}.md".format(tier_id)
        summary.append("| {} | {:,} | [查看项目]({}) |".format(title, len(selected), filename))
        output[filename] = "\n".join(["<!-- Generated by scripts/build_lists.py. -->", "# " + title, "", "[返回首页](../../README.md) · [完整目录](../all.md)", "", "本层共 {:,} 个项目，按准确 Star 数降序排列。核对深度与关注度分别展示。".format(len(selected)), "", catalog_table(selected, repositories, titles)])
    summary += ["", "[完整分页目录](lists/all.md) · [机器可读索引](data/catalog.json)", "", "## 分类导航", "", "| 分类 | 全部项目 | 已核对高星精选 | 范围 |", "| --- | ---: | ---: | --- |"]
    index = ["<!-- Generated by scripts/build_lists.py. -->", "# 完整项目目录", "", "[返回首页](../README.md)", "", "共 {:,} 个有效仓库，按 Star 降序，每页最多 200 条。".format(len(active)), ""]
    page_count = (len(active) + 199) // 200
    for i in range(page_count):
        selected = active[i * 200:(i + 1) * 200]
        index.append("- [第 {} 页（第 {}–{} 条）](pages/{:02d}.md)".format(i + 1, i * 200 + 1, min((i + 1) * 200, len(active)), i + 1))
        output["lists/pages/{:02d}.md".format(i + 1)] = "\n".join(["<!-- Generated by scripts/build_lists.py. -->", "# 全部项目 · 第 {} / {} 页".format(i + 1, page_count), "", "[返回目录](../all.md) · [返回首页](../../README.md)", "", catalog_table(selected, repositories, titles)])
    output["lists/all.md"] = "\n".join(index) + "\n"
    records = []
    for p in active:
        m = repositories[p["github"].lower()]
        records.append({"github": p["github"], "url": "https://github.com/" + p["github"], "stars": m["stars"], "tier": star_tier(m["stars"]), "category": p["category"], "kind": p.get("kind", "application"), "education_relation": p["education_relation"], "education_use": p["education_use"], "upstream_description": p.get("upstream_description", ""), "review_level": p["review"]["level"], "status": p["status"], "fetched_at": m["fetched_at"]})
    output["data/catalog.json"] = json.dumps({"schema_version": 1, "generated_from": stamp, "count": len(records), "projects": records}, ensure_ascii=False, indent=2) + "\n"
    previews = []
    for category in config["categories"]:
        selected = [p for p in active if p["category"] == category["id"]]
        reviewed = [p for p in groups["main"] if p["category"] == category["id"]]
        filename = "lists/{}.md".format(category["id"])
        summary.append("| [{}]({}) | {:,} | {} | {} |".format(md(category["title"]), filename, len(selected), len(reviewed), md(category["description"])))
        page = ["<!-- Generated by scripts/build_lists.py. Edit data/projects/*.yml instead. -->", "# {}".format(category["title"]), "", category["description"], "", "[返回首页](../README.md) · [收录标准](../docs/selection-policy.md)", "", "分类共 {:,} 个项目。批量条目的教育用途为分类建议，原文简介和检索依据保留在 YAML；未逐项核对的条目如实标记。".format(len(selected)), ""]
        if selected:
            page += [catalog_table(selected, repositories, titles)]
        else:
            page += ["暂无记录。", ""]
        if reviewed:
            page += ["## 已核对精选详情", ""]
            for p in reviewed:
                page += [details(p, repositories.get(p["github"].lower(), {}), policy, reference_time, baseline), ""]
            previews += ["### {}".format(category["title"]), "", table(reviewed[:3], repositories), "", "[查看完整分类]({})".format(filename), ""]
        output[filename] = "\n".join(page).rstrip() + "\n"
    for group, title in (("watchlist", "观察清单"), ("candidates", "待审核项目"), ("retired", "归档与移出项目")):
        page = ["<!-- Generated by scripts/build_lists.py. -->", "# " + title, "", "[返回首页](../README.md)", "", "本页项目不进入已核对高 Star 精选。状态原因见各条目。", ""]
        if groups[group]:
            page += [table(groups[group], repositories), ""]
            for p in groups[group]:
                page += [details(p, repositories.get(p["github"].lower(), {}), policy, reference_time, baseline), ""]
        else:
            page += ["暂无记录。", ""]
        output["lists/{}.md".format(group)] = "\n".join(page).rstrip() + "\n"
    header = (root / "templates/header.md").read_text(encoding="utf-8").strip()
    footer = (root / "templates/footer.md").read_text(encoding="utf-8").strip()
    output["README.md"] = "<!-- Generated by scripts/build_lists.py. Edit templates/ and data/ instead. -->\n" + header + "\n\n" + "\n".join(summary) + "\n\n## 分类精选\n\n" + "\n".join(previews) + "\n" + footer + "\n"
    return output


def main():
    parser = argparse.ArgumentParser(description="生成教育项目分类清单")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="只检查生成文件是否与数据一致")
    args = parser.parse_args()
    try:
        output = render(args.root)
    except (ValueError, TypeError, OSError, KeyError, yaml.YAMLError) as exc:
        raise SystemExit(str(exc))
    different = []
    for name, text in output.items():
        path = args.root / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                different.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    expected = {args.root / name for name in output if name.startswith("lists/")}
    extras = set((args.root / "lists").rglob("*.md")) - expected
    if args.check:
        different += [str(p.relative_to(args.root)) for p in sorted(extras)]
        if different:
            raise SystemExit("Generated files are stale: " + ", ".join(different))
    else:
        for path in extras:
            path.unlink()
    print("{} {} catalog files.".format("Checked" if args.check else "Generated", len(output)))


if __name__ == "__main__":
    main()
