#!/usr/bin/env python3
"""Compare dependency findings against the target; report the full backlog separately."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "dependency_security", Path(__file__).with_name("check-dependency-security.py")
)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


def shared_observations(raw: dict) -> dict:
    """Identical package versions use the same observations on both sides."""
    observations = {}
    for result in raw["results"]:
        for entry in result["packages"]:
            package = entry["package"]
            ecosystem = package.get("ecosystem", "GIT")
            key = (
                ecosystem,
                POLICY.package_name(package["name"], ecosystem),
                package.get("version", package.get("commit", "")),
            )
            records = observations.setdefault(key, {})
            for vulnerability in entry.get("vulnerabilities", []):
                records[vulnerability["id"]] = vulnerability
    for result in raw["results"]:
        for entry in result["packages"]:
            package = entry["package"]
            ecosystem = package.get("ecosystem", "GIT")
            key = (
                ecosystem,
                POLICY.package_name(package["name"], ecosystem),
                package.get("version", package.get("commit", "")),
            )
            entry["vulnerabilities"] = list(observations[key].values())
    return raw


def paired_scan(root: Path, base: Path, scanner: Path, temporary: Path):
    rules = json.loads((root / "ci/dependency-security-sources.json").read_text())[
        "inherited_lockfiles"
    ]
    inventories, owners, maps, unresolved = [], {}, {}, {}
    for side, checkout in (("base", base), ("candidate", root)):
        work = temporary / side
        work.mkdir()
        inherited = rules
        if side == "base":
            previous_rules = checkout / "ci/dependency-security-sources.json"
            if previous_rules.exists():
                inherited = json.loads(previous_rules.read_text())[
                    "inherited_lockfiles"
                ]
            else:
                # Audited rollout bases predate this configuration. Components
                # absent from that old tree contribute no old findings.
                inherited = [name for name in rules if (checkout / name).exists()]
        files, sources, unknown = POLICY.inventory_files(checkout, work, inherited)
        maps[side] = {
            str(Path(path).resolve()): manifest for path, manifest in sources.items()
        }
        unresolved[side] = unknown
        for file in files:
            owners.setdefault(str(file.resolve()), []).append(side)
            inventories.append((file, str(file) in sources))
    if not inventories:
        return {side: {"results": []} for side in maps}, maps, unresolved
    config = temporary / "scanner.toml"
    config.write_text("")
    output = temporary / "scan.json"
    command = [
        str(scanner),
        "scan",
        "source",
        f"--config={config}",
        "--all-vulns",
        "--all-packages",
        "--format=json",
        f"--output-file={output}",
    ]
    command += [
        f"--lockfile={'osv-scanner:' if synthetic else ''}{file}"
        for file, synthetic in inventories
    ]
    result = subprocess.run(command, cwd=root, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"OSV-Scanner failed with exit code {result.returncode}")
    raw = json.loads(output.read_text())
    if not isinstance(raw.get("results"), list):
        raise TypeError("Scanner report must contain a results array")
    raw = shared_observations(raw)
    split = {side: {"results": []} for side in maps}
    for result in raw["results"]:
        source = Path(result["source"]["path"])
        source = source if source.is_absolute() else root / source
        key = str(source.resolve())
        if key not in owners:
            raise ValueError(f"Scanner source was not a supplied inventory: {source}")
        for side in owners[key]:
            item = copy.deepcopy(result)
            item["source"]["path"] = key
            split[side]["results"].append(item)
    return split, maps, unresolved


def compare(base: dict, candidate: dict) -> dict:
    old = base["blocking"] + base["accepted"]
    current = candidate["blocking"] + candidate["accepted"]
    # Join aliases transitively so a GHSA/CVE naming change is not a new issue.
    aliases = {}

    def canonical(identifier):
        aliases.setdefault(identifier, identifier)
        if aliases[identifier] != identifier:
            aliases[identifier] = canonical(aliases[identifier])
        return aliases[identifier]

    for finding in old + current:
        identifiers = {finding["advisory"], *finding.get("aliases", [])}
        anchor = min(identifiers)
        for identifier in identifiers:
            aliases[canonical(identifier)] = canonical(anchor)

    def identity(finding):
        return (
            canonical(finding["advisory"]),
            finding["ecosystem"],
            POLICY.package_name(finding["package"], finding["ecosystem"]),
            finding["manifest"],
        )

    previous = {identity(item) for item in old}
    proposed = {identity(item) for item in current}
    introduced = [item for item in current if identity(item) not in previous]
    retained = [item for item in current if identity(item) in previous]
    resolved = [item for item in old if identity(item) not in proposed]
    blocking = [item for item in introduced if "exception" not in item]
    return {
        "mode": "comparison",
        "status": "blocked" if blocking else "passed",
        "introduced": introduced,
        "retained": retained,
        "resolved": resolved,
        "blocking": blocking,
        "accepted": candidate["accepted"],
        "base": {k: base[k] for k in ("packages_scanned", "sources")},
        "candidate": {k: candidate[k] for k in ("packages_scanned", "sources")},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--base-root",
        type=Path,
        help="Target/pre-push checkout; omitted for an advisory inventory",
    )
    parser.add_argument(
        "--scanner", type=Path, help="Use an installed OSV-Scanner for local validation"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(tempfile.gettempdir()) / "dependency-regressions.json",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        scanner = args.scanner.resolve() if args.scanner else POLICY.install_scanner()
        exceptions = POLICY.load_exceptions(
            root / "ci/dependency-security-exceptions.json"
        )
        with tempfile.TemporaryDirectory(prefix="dependency-comparison-") as directory:
            work = Path(directory)
            if args.base_root:
                base = args.base_root.resolve()
                raw, maps, unresolved = paired_scan(root, base, scanner, work)
                assessment = compare(
                    POLICY.assess(raw["base"], [], base, maps["base"]),
                    POLICY.assess(
                        raw["candidate"], exceptions, root, maps["candidate"]
                    ),
                )
                assessment["unresolved_build_requirements"] = unresolved
            else:
                raw, mapping = POLICY.run_scan(root, scanner, work)
                assessment = POLICY.assess(raw, exceptions, root, mapping)
                assessment.update(
                    mode="inventory",
                    status="reported",
                    unresolved_build_requirements=raw.get(
                        "unresolved_build_requirements", []
                    ),
                )
        assessment["scanner_version"] = POLICY.SCANNER_VERSION
        categories = (
            ("introduced", "retained", "resolved") if args.base_root else ("blocking",)
        )
        for category in categories:
            for finding in assessment[category]:
                print(f"{category.upper()}: {json.dumps(finding, sort_keys=True)}")
        if args.base_root:
            message = (
                f"Dependency comparison: {assessment['status']}; "
                f"{len(assessment['blocking'])} new unaccepted, "
                f"{len(assessment['retained'])} retained, {len(assessment['resolved'])} resolved finding instances."
            )
        else:
            message = (
                f"Dependency inventory: advisory; {len(assessment['blocking'])} unaccepted, "
                f"{len(assessment['accepted'])} explicitly accepted finding instances."
            )
        print(message)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
                summary.write(
                    "## Dependency security\n\n"
                    + message
                    + "\n\nDownload the dependency-security artifact for exact findings and unresolved coverage.\n"
                )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        RuntimeError,
    ) as error:
        assessment = {
            "status": "error",
            "error": str(error),
            "scanner_version": POLICY.SCANNER_VERSION,
        }
        print(f"Dependency comparison failed: {error}", file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(assessment, indent=2) + "\n")
    return {"passed": 0, "reported": 0, "blocked": 1, "error": 2}[assessment["status"]]


if __name__ == "__main__":
    sys.exit(main())
