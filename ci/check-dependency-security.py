#!/usr/bin/env python3
"""Audit candidate lockfiles and explicit build pins without changing dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

SCANNER_VERSION = "2.7.0"
SCANNER_SHA256 = {
    "linux_amd64": "160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b",
    "linux_arm64": "4061ef4c021ed3c47f203b818f337e351336cc5cd67c0274fc36bd1dfc728dd7",
    "darwin_arm64": "d4926ef8da134332543be276dff157e4c170f99ad91fc48e89448a8816bdf70b",
}
LOCKFILES = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "pdm.lock",
    "pylock.toml",
    "Cargo.lock",
    "go.mod",
    "composer.lock",
    "Gemfile.lock",
}


def tracked_files(root: Path) -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return [name.decode() for name in output.split(b"\0") if name]


def install_scanner() -> Path:
    machine = {"x86_64": "amd64", "aarch64": "arm64"}.get(
        platform.machine(), platform.machine()
    )
    target = f"{platform.system().lower()}_{machine}"
    expected = SCANNER_SHA256[target]
    destination = (
        Path(tempfile.gettempdir())
        / f"cybergold-osv-scanner-{SCANNER_VERSION}-{target}"
    )
    if (
        not destination.exists()
        or hashlib.sha256(destination.read_bytes()).hexdigest() != expected
    ):
        url = f"https://github.com/google/osv-scanner/releases/download/v{SCANNER_VERSION}/osv-scanner_{target}"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(
                f"OSV-Scanner {SCANNER_VERSION} download checksum mismatch"
            )
        destination.write_bytes(data)
        destination.chmod(0o755)
    return destination


def load_exceptions(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if data.get("schemaVersion") != 1 or not isinstance(data.get("exceptions"), list):
        raise ValueError(
            "Exception file must contain schemaVersion 1 and an exceptions array"
        )
    for item in data["exceptions"]:
        for key in (
            "advisory",
            "ecosystem",
            "package",
            "manifest",
            "reason",
            "owner_approval",
            "review_trigger",
        ):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"Exception requires a nonempty {key}")
        for key in ("advisory", "ecosystem", "package", "manifest"):
            if any(char in item[key] for char in "*?["):
                raise ValueError(
                    f"Exception {key} must be an exact value, not a wildcard"
                )
    return data["exceptions"]


def package_name(value: str, ecosystem: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower() if ecosystem == "PyPI" else value


def assess(
    report: dict, exceptions: list[dict], root: Path, source_map: dict | None = None
) -> dict:
    if not isinstance(report, dict) or "results" not in report:
        raise ValueError("Scanner report must contain a results array")
    results = report["results"]
    if not isinstance(results, list):
        raise TypeError("Scanner results must be an array")
    accepted, blocking, sources, seen = [], [], set(), set()
    packages_scanned = 0
    for result in results:
        source = result["source"]["path"]
        source = (source_map or {}).get(source, source)
        manifest = (
            os.path.relpath(source, root) if Path(source).is_absolute() else source
        )
        sources.add(manifest)
        packages = result["packages"]
        if not isinstance(packages, list):
            raise TypeError(f"Scanner packages must be an array for {manifest}")
        packages_scanned += len(packages)
        for entry in packages:
            package = entry["package"]
            ecosystem = package.get("ecosystem", "GIT")
            name = package["name"]
            for vulnerability in entry.get("vulnerabilities", []):
                ids = {vulnerability["id"], *vulnerability.get("aliases", [])}
                advisory = next(
                    iter(sorted(x for x in ids if x.startswith("GHSA-"))),
                    vulnerability["id"],
                )
                finding = {
                    "advisory": advisory,
                    "ecosystem": ecosystem,
                    "package": name,
                    "version": package.get("version", package.get("commit", "")),
                    "manifest": manifest,
                    "severity": vulnerability.get("database_specific", {}).get(
                        "severity", "UNKNOWN"
                    ),
                }
                identity = tuple(
                    finding[key]
                    for key in (
                        "advisory",
                        "ecosystem",
                        "package",
                        "version",
                        "manifest",
                    )
                )
                if identity in seen:
                    continue
                seen.add(identity)
                exception = next(
                    (
                        item
                        for item in exceptions
                        if item["advisory"] in ids
                        and item["ecosystem"] == ecosystem
                        and item["manifest"] == manifest
                        and package_name(item["package"], ecosystem)
                        == package_name(name, ecosystem)
                    ),
                    None,
                )
                if exception:
                    accepted.append({**finding, "exception": exception})
                else:
                    blocking.append(finding)
    return {
        "status": "blocked" if blocking else "passed",
        "scanner_version": SCANNER_VERSION,
        "packages_scanned": packages_scanned,
        "sources": sorted(sources),
        "accepted": accepted,
        "blocking": blocking,
    }


def inventory_files(
    root: Path, temporary: Path
) -> tuple[list[Path], dict[str, str], list[dict]]:
    files, source_map = [], {}
    tracked = tracked_files(root)
    inherited = json.loads((root / "ci/dependency-security-sources.json").read_text())[
        "inherited_lockfiles"
    ]
    tracked += inherited
    unresolved_build_requirements = []
    for name in tracked:
        path = root / name
        if path.name in LOCKFILES or (
            path.suffix == ".txt" and "requirements" in path.name
        ):
            files.append(path)
        if path.name != "pyproject.toml":
            continue
        project = tomllib.loads(path.read_text())
        packages = []
        for requirement in project.get("build-system", {}).get("requires", []):
            pin = re.fullmatch(
                r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([A-Za-z0-9_.+!-]+)", requirement
            )
            if not pin:
                unresolved_build_requirements.append(
                    {"manifest": name, "requirement": requirement}
                )
                continue
            packages.append(
                {"package": {"name": pin[1], "version": pin[2], "ecosystem": "PyPI"}}
            )
        if packages:
            inventory = temporary / f"build-{len(files)}.json"
            inventory.write_text(json.dumps({"results": [{"packages": packages}]}))
            files.append(inventory)
            source_map[str(inventory)] = str(path)
    # Query committed submodule identities as well as the lockfiles inside checked-out submodules.
    gitlinks = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z"], cwd=root
    ).split(b"\0")
    for record in gitlinks:
        if not record.startswith(b"160000 "):
            continue
        metadata, name = record.decode().split("\t", 1)
        commit = metadata.split()[1]
        inventory = temporary / f"git-{len(files)}.json"
        inventory.write_text(
            json.dumps(
                {
                    "results": [
                        {"packages": [{"package": {"name": name, "commit": commit}}]}
                    ]
                }
            )
        )
        files.append(inventory)
        source_map[str(inventory)] = name
    return files, source_map, unresolved_build_requirements


def run_scan(root: Path, scanner: Path, temporary: Path) -> tuple[dict, dict]:
    files, source_map, unresolved = inventory_files(root, temporary)
    if not files:
        return {"results": [], "unresolved_build_requirements": unresolved}, source_map
    config = temporary / "scanner.toml"
    config.write_text(
        ""
    )  # Policy exceptions are evaluated below and remain visible in the report.
    output = temporary / "scanner.json"
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
    for path in files:
        extractor = "osv-scanner:" if str(path) in source_map else ""
        command.append(f"--lockfile={extractor}{path}")
    result = subprocess.run(command, cwd=root, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"OSV-Scanner failed with exit code {result.returncode}")
    report = json.loads(output.read_text())
    if "results" not in report:
        raise ValueError(
            "Scanner returned no results field for the supplied dependency inventories"
        )
    report["unresolved_build_requirements"] = unresolved
    return report, source_map


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--scanner",
        type=Path,
        help="Use an already installed OSV-Scanner for local validation",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(tempfile.gettempdir()) / "cybergold-dependency-security.json",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        exceptions = load_exceptions(root / "ci/dependency-security-exceptions.json")
        scanner = args.scanner.resolve() if args.scanner else install_scanner()
        with tempfile.TemporaryDirectory(
            prefix="cybergold-dependency-security-"
        ) as directory:
            raw, source_map = run_scan(root, scanner, Path(directory))
            assessment = assess(raw, exceptions, root, source_map)
            assessment["unresolved_build_requirements"] = raw.get(
                "unresolved_build_requirements", []
            )
        for requirement in assessment["unresolved_build_requirements"]:
            print(
                f"UNRESOLVED BUILD DECLARATION (not audited): {json.dumps(requirement, sort_keys=True)}"
            )
        for disposition in ("accepted", "blocking"):
            for finding in assessment[disposition]:
                print(f"{disposition.upper()}: {json.dumps(finding, sort_keys=True)}")
        print(
            f"Dependency security: {assessment['status']}; {len(assessment['blocking'])} blocking, "
            f"{len(assessment['accepted'])} explicitly accepted; {assessment['packages_scanned']} package records audited."
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
            "scanner_version": SCANNER_VERSION,
        }
        print(f"Dependency security check failed: {error}", file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(assessment, indent=2) + "\n")
    return {"passed": 0, "blocked": 1, "error": 2}[assessment["status"]]


if __name__ == "__main__":
    sys.exit(main())
