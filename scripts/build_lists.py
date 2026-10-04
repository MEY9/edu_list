"""Generate deterministic Markdown from reviewed records and cached metrics."""
import argparse
import json
import yaml
from datetime import timedelta
from pathlib import Path

from catalog import ROOT, RELATIONS, REVIEW_LEVELS, bucket, load_catalog, load_metrics, local_time, md, parse_time, validate


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


def render(root=ROOT):
    config, projects = load_catalog(root)
    metrics = load_metrics(root)
    errors = validate(config, projects, metrics)
    if errors:
        raise ValueError("\n".join(errors))
    repositories = metrics["repositories"]
    policy = config["policy"]
    stamp = metrics.get("last_attempt_at")
    # No wall-clock dependence: --check stays stable between scheduled refreshes.
    reference_time = parse_time(stamp or "1970-01-01T00:00:00Z")
    previous = previous_snapshot(root, metrics)
    baseline = previous[1] if previous else None
    projects.sort(key=lambda p: (-repositories.get(p["github"].lower(), {}).get("stars", -1), p["github"].lower()))
    groups = {name: [] for name in ("main", "watchlist", "candidates", "retired")}
    for p in projects:
        groups[bucket(p, repositories.get(p["github"].lower(), {}), policy["min_stars"])].append(p)
    output = {}
    summary = ["## 清单状态", "", "主清单 **{}** 个项目；观察清单 **{}** 个；待审核 **{}** 个；归档／移出 **{}** 个。".format(*(len(groups[k]) for k in ("main", "watchlist", "candidates", "retired"))), "",
               "数据更新尝试：{}。每个条目的成功获取时间见分类页。".format(local_time(stamp) if stamp else "尚未获取"), "",
               "Star 变化基线：{}。".format(local_time(previous[0]) if previous else "尚无上一期快照，暂不计算增长"), "",
               "## 分类导航", "", "| 分类 | 主清单数量 | 范围 |", "| --- | ---: | --- |"]
    previews = []
    for category in config["categories"]:
        selected = [p for p in groups["main"] if p["category"] == category["id"]]
        filename = "lists/{}.md".format(category["id"])
        summary.append("| [{}]({}) | {} | {} |".format(md(category["title"]), filename, len(selected), md(category["description"])))
        page = ["<!-- Generated by scripts/build_lists.py. Edit data/projects/*.yml instead. -->", "# {}".format(category["title"]), "", category["description"], "", "[返回首页](../README.md) · [收录标准](../docs/selection-policy.md)", "", "按 Star 降序排列。许可证标识来自 GitHub API；实际使用请核对上游条款。", ""]
        if selected:
            page += [table(selected, repositories), "## 项目详情", ""]
            for p in selected:
                page += [details(p, repositories.get(p["github"].lower(), {}), policy, reference_time, baseline), ""]
            previews += ["### {}".format(category["title"]), "", table(selected[:3], repositories), "", "[查看完整分类]({})".format(filename), ""]
        else:
            page += ["暂无符合当前门槛的已收录项目。欢迎通过 Issue 推荐。", ""]
        output[filename] = "\n".join(page).rstrip() + "\n"
    for group, title in (("watchlist", "观察清单"), ("candidates", "待审核项目"), ("retired", "归档与移出项目")):
        page = ["<!-- Generated by scripts/build_lists.py. -->", "# " + title, "", "[返回首页](../README.md)", "", "本页项目不进入高 Star 主清单。状态原因见各条目。", ""]
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
    extras = set((args.root / "lists").glob("*.md")) - expected
    if args.check:
        different += [str(p.relative_to(args.root)) for p in sorted(extras)]
        if different:
            raise SystemExit("Generated files are stale: " + ", ".join(different))
    else:
        for path in extras:
            path.unlink()
    print("{} {} Markdown files.".format("Checked" if args.check else "Generated", len(output)))


if __name__ == "__main__":
    main()
