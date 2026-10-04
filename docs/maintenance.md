# 维护说明

## 数据来源

`data/projects/*.yml` 是人工维护的数据源；`data/categories.yml` 定义分类与门槛。`data/metrics.json` 保存 GitHub 公开仓库 API 元数据；`data/snapshots/YYYY-MM-DD.json` 保存当天成功刷新快照。

首页和 `lists/` 由 `scripts/build_lists.py` 生成，修改介绍请编辑 `templates/header.md` 和 `templates/footer.md`。同一天再次成功刷新会覆盖该日快照；增长使用更早的最近快照。没有基线时不显示增长值。

## 安装与运行

Python 3.9+，唯一 Python 依赖为 PyYAML。推荐使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/validate.py
python scripts/build_lists.py
python -m unittest discover -s tests -v
python scripts/build_lists.py --check
```

数据抓取需要联网：

```bash
python scripts/fetch_metrics.py
python scripts/validate.py
python scripts/build_lists.py
```

可以使用环境变量 `GITHUB_TOKEN` 提供有公开仓库读取权限的令牌；不要把令牌写入 YAML、JSON、日志或提交。匿名 API 有额度限制。生成脚本读取缓存，所以不联网也能重新生成页面。

## GitHub Actions

- `Validate catalog`：在推送或 PR 时检查数据、测试脚本、确认生成文件一致，只有仓库读取权限。
- `Update GitHub metrics`：每周一北京时间 10:23（UTC 02:23）运行，也支持 Actions 页面手动运行；分类、项目数据和脚本更新推送到 main 时也会运行。
- 更新流程仅刷新已有记录，成功后由 GitHub Actions bot 提交数据与清单，不自动搜索或批准新项目。
- 定时任务由 GitHub 调度，可能延迟；长期没有活动的公开仓库定时任务可能被暂停。
- 若设置保护分支禁止 bot 直接推送，需将更新流程改为提交 PR。若仓库／组织限制 Actions 写入，则需要允许此工作流的 `contents: write`。
- bot 使用 `GITHUB_TOKEN` 推送通常不会再次触发 push 工作流，所以更新任务本身也执行测试和生成一致性检查。

## 故障处理

401／403：检查令牌访问权限和 API 额度。404：核对迁移或删除，不直接假定项目不可用。网络、429 和部分 5xx 会有限次数重试；重试失败保留历史指标。定时流程失败时没有新的提交，下一次可手动重跑。

重复 YAML 键、未知字段、重复仓库、分类错误和无效时间会被检查拒绝。新项目提交候选状态即可，维护者核对后修改 `status`，再更新指标。

## 首批资料

初版核对 26 个条目，其中 22 个符合主清单门槛，Gibbon 与当前 Scratch Editor 为低 Star 观察项目；GeoGebra 因许可范围待核对保留为候选；旧 Scratch GUI 已归档。

Blockly 与 Open edX 已使用 API 返回的当前仓库全名。所有初始条目的上游 README 来源及核对方式见对应 YAML。没有运行这些第三方项目，也没有调用生成模型或付费 API。

结构参考：[Awesome](https://github.com/sindresorhus/awesome)、[Awesome Selfhosted Data](https://github.com/awesome-selfhosted/awesome-selfhosted-data)、[Best-of Generator](https://github.com/best-of-lists/best-of-generator)。GitHub 元数据字段参考 [官方 API](https://docs.github.com/en/rest/repos/repos#get-a-repository)。
