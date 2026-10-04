"""Fetch only public repository metadata; never executes collected projects."""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from catalog import ROOT, load_catalog, load_metrics, validate, write_json


def normalize(payload, fetched_at):
    return {
        "repository_id": payload["id"],
        "full_name": payload["full_name"],
        "stars": payload["stargazers_count"],
        "forks": payload["forks_count"],
        "language": payload.get("language"),
        "license": (payload.get("license") or {}).get("spdx_id"),
        "archived": payload["archived"],
        "disabled": payload.get("disabled", False),
        "pushed_at": payload.get("pushed_at"),
        "updated_at": payload.get("updated_at"),
        "fetched_at": fetched_at,
        "fetch_status": "ok",
        "source": payload.get("_source", "https://api.github.com/repos/" + payload["full_name"]),
    }


class GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse
        if urlparse(newurl).scheme != "https" or urlparse(newurl).hostname != "api.github.com":
            raise ValueError("Refusing API redirect outside api.github.com")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_repository(repo, token=None, opener=None, sleeper=time.sleep):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "edu-list-metadata"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request("https://api.github.com/repos/" + repo, headers=headers)
    open_url = opener or urllib.request.build_opener(GitHubRedirectHandler()).open
    for attempt in range(3):
        try:
            with open_url(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError("GitHub HTTP {} for {} (check API quota or repository access)".format(exc.code, repo)) from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError("Network timeout/error for {}".format(repo)) from None
        sleeper(2 ** attempt)


def refresh(projects, existing, fetcher, fetched_at):
    repositories = dict(existing.get("repositories", {}))
    failures = []
    for p in projects:
        key = p["github"].lower()
        try:
            repositories[key] = normalize(fetcher(p["github"]), fetched_at)
        except (RuntimeError, KeyError, ValueError, TypeError) as exc:
            # Preserve last known counts and their original timestamp on failure.
            previous = dict(repositories.get(key, {}))
            previous.update(fetch_status="error", last_error_at=fetched_at, last_error=str(exc))
            repositories[key] = previous
            failures.append("{}: {}".format(p["github"], exc))
    keys = {p["github"].lower() for p in projects}
    return {"schema_version": 1, "last_attempt_at": fetched_at,
            "repositories": {k: v for k, v in repositories.items() if k in keys}}, failures


def fetch_batch(repos, token, opener=None, sleeper=time.sleep):
    """Read 50 repositories in one GraphQL request, without connection pagination."""
    fields = "databaseId nameWithOwner stargazerCount forkCount isArchived isDisabled pushedAt updatedAt primaryLanguage { name } licenseInfo { spdxId }"
    aliases = []
    for i, repo in enumerate(repos):
        owner, name = repo.split("/")
        aliases.append("r%d: repository(owner: %s, name: %s) { %s }" % (i, json.dumps(owner), json.dumps(name), fields))
    query = "query { " + " ".join(aliases) + " }"
    request = urllib.request.Request("https://api.github.com/graphql", data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "edu-list-metadata"}, method="POST")
    open_url = opener or urllib.request.build_opener(GitHubRedirectHandler()).open
    for attempt in range(3):
        try:
            with open_url(request, timeout=60) as response:
                result = json.load(response)
            if not isinstance(result.get("data"), dict):
                raise RuntimeError("GitHub GraphQL query returned no data; check API access/schema/quota")
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError("GitHub GraphQL HTTP {}".format(exc.code)) from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError("GitHub GraphQL network timeout/error") from None
        sleeper(2 ** attempt)
    payloads = {}
    for i, repo in enumerate(repos):
        node = result["data"].get("r%d" % i)
        if not node or not node.get("databaseId"):
            continue
        payloads[repo.lower()] = {"_source": "https://api.github.com/graphql", "id": node["databaseId"], "full_name": node["nameWithOwner"],
            "stargazers_count": node["stargazerCount"], "forks_count": node["forkCount"],
            "archived": node["isArchived"], "disabled": node["isDisabled"],
            "pushed_at": node.get("pushedAt"), "updated_at": node.get("updatedAt"),
            "language": (node.get("primaryLanguage") or {}).get("name"),
            "license": {"spdx_id": (node.get("licenseInfo") or {}).get("spdxId")}}
    return payloads


def refresh_batched(projects, existing, token, fetched_at, batch_fetcher=fetch_batch, sleeper=time.sleep):
    payloads = {}
    errors = {}
    for start in range(0, len(projects), 50):
        names = [p["github"] for p in projects[start:start + 50]]
        try:
            payloads.update(batch_fetcher(names, token))
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            errors.update({name.lower(): str(exc) for name in names})
        print("Fetched batch {}/{}".format(start // 50 + 1, (len(projects) + 49) // 50), flush=True)
        if start + 50 < len(projects):
            sleeper(1)
    def cached_fetch(repo):
        key = repo.lower()
        if key not in payloads:
            raise RuntimeError(errors.get(key, "Repository missing from GraphQL response; verify access or migration"))
        return payloads[key]
    return refresh(projects, existing, cached_fetch, fetched_at)


def main():
    parser = argparse.ArgumentParser(description="更新 GitHub Star 等客观数据")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--rest", action="store_true", help="强制逐仓库 REST 抓取（大清单需足够 API 配额）")
    args = parser.parse_args()
    config, projects = load_catalog(args.root)
    errors = validate(config, projects)
    if errors:
        raise SystemExit("\n".join(errors))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    token = os.environ.get("GITHUB_TOKEN")
    if token and not args.rest:
        result, failures = refresh_batched(projects, load_metrics(args.root), token, stamp)
    else:
        if not token and len(projects) > 50:
            raise SystemExit("Large catalog requires GITHUB_TOKEN for batched GraphQL metadata refresh.")
        result, failures = refresh(projects, load_metrics(args.root), lambda repo: fetch_repository(repo, token), stamp)
    write_json(args.root / "data/metrics.json", result)
    for error in failures:
        print("ERROR: " + error)
    if failures:
        raise SystemExit("Refresh incomplete; previous metrics preserved. No snapshot created.")
    write_json(args.root / "data/snapshots" / (stamp[:10] + ".json"), result)
    print("Updated {} repositories; snapshot {}.".format(len(projects), stamp[:10]))


if __name__ == "__main__":
    main()
