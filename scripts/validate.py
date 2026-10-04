import argparse
import yaml
from pathlib import Path
from catalog import ROOT, load_catalog, load_metrics, validate


def main():
    parser = argparse.ArgumentParser(description="检查项目字段、重复记录和分类")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        config, projects = load_catalog(args.root)
        errors = validate(config, projects, load_metrics(args.root))
    except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
        errors = [str(exc)]
    for error in errors:
        print("ERROR: " + error)
    if errors:
        raise SystemExit(1)
    print("Validated {} projects in {} categories.".format(len(projects), len(config["categories"])))


if __name__ == "__main__":
    main()
