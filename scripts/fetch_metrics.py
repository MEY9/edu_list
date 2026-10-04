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
        "source": "https://api.github.com/repos/" + payload["full_name"],
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


def main():
    parser = argparse.ArgumentParser(description="更新 GitHub Star 等客观数据")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    config, projects = load_catalog(args.root)
    errors = validate(config, projects)
    if errors:
        raise SystemExit("\n".join(errors))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    token = os.environ.get("GITHUB_TOKEN")
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
