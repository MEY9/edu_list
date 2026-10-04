# 贡献指南

欢迎推荐对教学、学习、学校或培训有明确用途的 GitHub 项目。

## 推荐方式

直接使用 [推荐项目表单](https://github.com/MEY9/edu_list/issues/new/choose)，填写仓库地址、教育用途和上游依据。提交 Issue 不会自动收录。

熟悉 Git 的贡献者可以新增 `data/projects/owner--repo.yml`。文件名小写，按仓库全名命名。先搜索现有条目避免重复；仓库迁移时更新已有记录。

## 新条目模板

```yaml
schema_version: 1
name: 项目名称
github: owner/repo
description_zh: 一句话描述实际功能。
category: courseware
tags: [演示]
education_relation: adaptable
audience: [教师]
education_use: 描述具体教学任务，以及需要另外开发的部分。
cost: 说明本地、自托管和外部 API 的成本边界。
deployment: 说明运行环境和部署要求。
license_note: 核对上游代码、资源和服务的许可；未知部分写明。
status: candidate
status_reason: 等待维护者核对教育用途与收录条件。
review:
  level: readme_reviewed
  checked_at: '2026-10-05T00:00:00Z'
  method: 请填写实际核对方式，区分人或工具辅助；未运行时明确写明。
  sources:
    - https://github.com/owner/repo
```

模板日期只是格式示例，请改为实际核对时间。分类与审核枚举见 [收录标准](docs/selection-policy.md)。`status: accepted` 由维护者确认；不要将阅读 README 写成运行验证，也不要将工具辅助整理描述为人工实测。

## 本地检查

Python 3.9+：

```bash
python3 -m pip install -r requirements.txt
python3 scripts/validate.py
python3 scripts/build_lists.py
python3 -m unittest discover -s tests -v
python3 scripts/build_lists.py --check
```

修改生成数据后，提交相应 README 和分类页更新。不要直接修改生成区内容；首页介绍修改 `templates/`。新候选项目可以没有 Star 缓存，页面会显示“待获取”；维护者随后运行更新流程。

Star、Fork、推送时间与许可证标识保存在 `data/metrics.json`，应由脚本获取，不手工虚构数值。API 抓取需要联网，令牌仅通过环境变量提供，不能提交到仓库。
