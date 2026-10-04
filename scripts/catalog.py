"""Shared catalog loading, validation and selection rules (Python 3.9+)."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+\Z")
RELATIONS = {"native": "教育原生", "adaptable": "可用于教育"}
REVIEW_LEVELS = {"readme_reviewed": "资料核对", "code_reviewed": "代码核对", "run_verified": "运行验证"}
STATUSES = {"accepted", "candidate", "removed"}


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("Duplicate YAML key: {}".format(key))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def load_catalog(root=ROOT):
    config = load_yaml(root / "data/categories.yml")
    projects = []
    for path in sorted((root / "data/projects").glob("*.yml")):
        project = load_yaml(path)
        if not isinstance(project, dict):
            raise ValueError("{} must be a YAML mapping".format(path.name))
        project = dict(project, _file=path.name)
        projects.append(project)
    return config, projects


def load_metrics(root=ROOT):
    path = root / "data/metrics.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "repositories": {}}


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def local_time(value, date_only=False):
    if not value:
        return "未知"
    local = parse_time(value).astimezone(timezone(timedelta(hours=8)))
    return local.strftime("%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M:%S UTC+08:00")


def bucket(project, metric, min_stars):
    # A refresh cannot promote a candidate or reintroduce a manually removed item.
    if project["status"] == "removed":
        return "retired"
    if project["status"] == "candidate":
        return "candidates"
    if metric.get("archived") or metric.get("disabled"):
        return "retired"
    if type(metric.get("stars")) is not int:
        return "candidates"
    if metric["stars"] < min_stars:
        return "watchlist"
    return "main"


def validate(config, projects, metrics=None):
    errors = []
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        return ["categories.yml: unsupported schema_version"]
    policy = config.get("policy", {})
    for field in ("min_stars", "inactive_days"):
        if type(policy.get(field)) is not int or policy[field] < 1:
            errors.append("policy.{} must be a positive integer".format(field))
    categories = config.get("categories", [])
    ids = [c.get("id") for c in categories if isinstance(c, dict)]
    if len(ids) != len(categories) or len(set(ids)) != len(ids):
        errors.append("Categories must have unique ids")
    for c in categories:
        if not isinstance(c, dict) or not re.fullmatch(r"[a-z][a-z0-9-]*", str(c.get("id", ""))) or not c.get("title") or not c.get("description"):
            errors.append("Category id/title/description invalid")
    seen = set()
    required = {"schema_version", "name", "github", "description_zh", "category", "tags", "education_relation", "audience", "education_use", "cost", "deployment", "license_note", "status", "review"}
    optional = {"status_reason", "replacement", "_file"}
    canonical_ids = {}
    repositories = (metrics or {}).get("repositories", {})
    for p in projects:
        label = p.get("_file", "unknown")
        missing = required - set(p)
        unknown = set(p) - required - optional
        if missing or unknown:
            errors.append("{}: missing {}, unknown {}".format(label, sorted(missing), sorted(unknown)))
        repo = p.get("github", "")
        if not isinstance(repo, str) or not REPO_PATTERN.fullmatch(repo) or repo.split("/")[-1] in {".", ".."}:
            errors.append("{}: invalid github owner/repo".format(label))
            continue
        key = repo.lower()
        if key in seen:
            errors.append("{}: duplicate repository {}".format(label, repo))
        seen.add(key)
        if label != key.replace("/", "--") + ".yml":
            errors.append("{}: filename must match lowercase owner--repo.yml".format(label))
        if p.get("schema_version") != 1 or p.get("category") not in ids:
            errors.append("{}: invalid schema/category".format(label))
        if p.get("education_relation") not in RELATIONS or p.get("status") not in STATUSES:
            errors.append("{}: invalid relation/status".format(label))
        for field in ("name", "description_zh", "education_use", "cost", "deployment", "license_note"):
            if not isinstance(p.get(field), str) or not p[field].strip():
                errors.append("{}: {} must be nonempty text".format(label, field))
        for field in ("tags", "audience"):
            values = p.get(field)
            if not isinstance(values, list) or not values or any(not isinstance(x, str) or not x.strip() for x in values):
                errors.append("{}: {} must be a nonempty list of text".format(label, field))
        if p.get("status") in {"candidate", "removed"} and not p.get("status_reason"):
            errors.append("{}: candidate/removed requires status_reason".format(label))
        replacement = p.get("replacement")
        if replacement is not None and (not isinstance(replacement, str) or not REPO_PATTERN.fullmatch(replacement)):
            errors.append("{}: invalid replacement".format(label))
        review = p.get("review", {})
        if not isinstance(review, dict):
            errors.append("{}: review must be a mapping".format(label))
            continue
        if review.get("level") not in REVIEW_LEVELS or not review.get("method"):
            errors.append("{}: review level/method required".format(label))
        try:
            parse_time(review["checked_at"])
        except (KeyError, TypeError, ValueError, AttributeError):
            errors.append("{}: invalid review.checked_at".format(label))
        sources = review.get("sources", [])
        if not isinstance(sources, list) or not sources:
            errors.append("{}: review.sources required".format(label))
        else:
            for source in sources:
                url = urlparse(source) if isinstance(source, str) else None
                if not url or url.scheme != "https" or not url.hostname or url.username or url.password:
                    errors.append("{}: invalid source URL".format(label))
        m = repositories.get(key)
        if m:
            if type(m.get("stars")) is not int or m["stars"] < 0 or type(m.get("archived")) is not bool:
                errors.append("{}: invalid cached metrics".format(label))
            try:
                parse_time(m["fetched_at"])
            except (KeyError, TypeError, ValueError, AttributeError):
                errors.append("{}: invalid metrics.fetched_at".format(label))
            if m.get("repository_id") in canonical_ids:
                errors.append("{}: repository duplicates canonical id of {}".format(label, canonical_ids[m["repository_id"]]))
            elif m.get("repository_id"):
                canonical_ids[m["repository_id"]] = repo
    return errors


def md(value):
    text = " ".join(str(value).split())
    for char in ("\\", "|", "[", "]", "*", "_", "`", "<", ">"):
        text = text.replace(char, "\\" + char)
    return text
