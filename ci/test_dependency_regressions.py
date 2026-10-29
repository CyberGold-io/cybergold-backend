#!/usr/bin/env python3
"""Behavioral regressions for the owner-approved no-new-vulnerabilities rule."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "regressions", Path(__file__).with_name("check-dependency-regressions.py")
)
RULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RULE)
ADVISORY = "GHSA-1234-5678-9abc"


def finding(
    advisory=ADVISORY, version="1.0.0", manifest="package-lock.json", severity="LOW"
):
    return {
        "advisory": advisory,
        "aliases": [advisory, "CVE-2026-12345"],
        "ecosystem": "npm",
        "package": "child",
        "version": version,
        "manifest": manifest,
        "severity": severity,
    }


def assessment(*items):
    return {
        "blocking": list(items),
        "accepted": [],
        "packages_scanned": 1,
        "sources": ["package-lock.json"],
    }


class ComparisonTests(unittest.TestCase):
    def test_existing_findings_pass_without_accepting_them(self):
        result = RULE.compare(assessment(finding()), assessment(finding()))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["retained"]), 1)
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["blocking"], [])

    def test_resolving_findings_passes(self):
        result = RULE.compare(assessment(finding()), assessment())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["resolved"]), 1)

    def test_introduction_blocks_at_every_severity(self):
        for severity in ["LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"]:
            with self.subTest(severity=severity):
                result = RULE.compare(
                    assessment(), assessment(finding(severity=severity))
                )
                self.assertEqual(result["status"], "blocked")

    def test_equal_totals_do_not_hide_replacement_with_a_new_issue(self):
        new = finding("GHSA-aaaa-bbbb-cccc")
        new["aliases"] = [new["advisory"]]
        result = RULE.compare(assessment(finding()), assessment(new))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(result["introduced"]), 1)
        self.assertEqual(len(result["resolved"]), 1)

    def test_version_change_does_not_reopen_same_advisory(self):
        result = RULE.compare(
            assessment(finding()), assessment(finding(version="1.0.1"))
        )
        self.assertEqual(result["introduced"], [])
        self.assertEqual(result["resolved"], [])
        self.assertEqual(result["retained"][0]["version"], "1.0.1")

    def test_cve_and_ghsa_aliases_are_the_same_issue(self):
        old = finding("CVE-2026-12345")
        result = RULE.compare(assessment(old), assessment(finding()))
        self.assertEqual(result["status"], "passed")

    def test_new_component_is_not_covered_by_another_components_backlog(self):
        result = RULE.compare(
            assessment(finding()),
            assessment(finding(manifest="other/package-lock.json")),
        )
        self.assertEqual(result["status"], "blocked")

    def test_previously_resolved_issue_is_new_again(self):
        self.assertEqual(
            RULE.compare(assessment(), assessment(finding()))["status"], "blocked"
        )

    def test_risk_acceptance_does_not_claim_a_resolution(self):
        current = assessment()
        current["accepted"] = [
            {**finding(), "exception": {"owner_approval": "actual decision"}}
        ]
        result = RULE.compare(assessment(finding()), current)
        self.assertEqual(result["resolved"], [])
        self.assertEqual(len(result["accepted"]), 1)

    def test_pypi_package_spellings_are_normalized(self):
        old, new = finding(), finding()
        old.update(ecosystem="PyPI", package="Some_Package")
        new.update(ecosystem="PyPI", package="some-package")
        self.assertEqual(
            RULE.compare(assessment(old), assessment(new))["status"], "passed"
        )

    def test_explicit_acceptance_remains_an_introduced_finding(self):
        current = assessment()
        current["accepted"] = [
            {**finding(), "exception": {"owner_approval": "actual decision"}}
        ]
        result = RULE.compare(assessment(), current)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["introduced"]), 1)
        self.assertEqual(result["blocking"], [])

    def test_new_disclosure_is_shared_for_unchanged_package_versions(self):
        old = {
            "package": {"name": "child", "version": "1.0.0", "ecosystem": "npm"},
            "vulnerabilities": [],
        }
        new = copy.deepcopy(old)
        new["vulnerabilities"] = [{"id": ADVISORY}]
        raw = RULE.shared_observations(
            {"results": [{"packages": [old]}, {"packages": [new]}]}
        )
        self.assertEqual(
            raw["results"][0]["packages"][0]["vulnerabilities"], [{"id": ADVISORY}]
        )

    def test_advisories_are_not_copied_to_different_package_versions(self):
        clean = {"package": {"name": "child", "version": "2.0.0", "ecosystem": "npm"}}
        affected = {
            "package": {"name": "child", "version": "1.0.0", "ecosystem": "npm"},
            "vulnerabilities": [{"id": ADVISORY}],
        }
        raw = RULE.shared_observations({"results": [{"packages": [clean, affected]}]})
        self.assertEqual(raw["results"][0]["packages"][0]["vulnerabilities"], [])


class CommandTests(unittest.TestCase):
    def test_newly_used_inherited_component_is_introduced_even_if_vendored_before(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for side in ["base", "candidate"]:
                root = work / side
                root.mkdir()
                subprocess.run(["git", "init", "--quiet", str(root)], check=True)
                (root / "ci").mkdir()
                sources = [] if side == "base" else ["lib/parent/uv.lock"]
                (root / "ci/dependency-security-sources.json").write_text(
                    json.dumps({"inherited_lockfiles": sources})
                )
                lock = root / "lib/parent/uv.lock"
                lock.parent.mkdir(parents=True)
                lock.write_text("untracked parent inventory")
            scanner = work / "scanner"
            scanner.write_text(f"""#!{sys.executable}
import json, pathlib, sys
results = []
for argument in sys.argv:
    if argument.startswith('--lockfile='):
        path = argument.split('=', 1)[1]
        results.append({{'source': {{'path': path}}, 'packages': [{{'package': {{'name': 'child', 'version': '1.0.0', 'ecosystem': 'PyPI'}}, 'vulnerabilities': [{{'id': {ADVISORY!r}}}]}}]}})
output = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--output-file='))
pathlib.Path(output).write_text(json.dumps({{'results': results}}))
sys.exit(1)
""")
            scanner.chmod(0o755)
            temporary = work / "scan"
            temporary.mkdir()
            raw, maps, _ = RULE.paired_scan(
                work / "candidate", work / "base", scanner, temporary
            )
            result = RULE.compare(
                RULE.POLICY.assess(raw["base"], [], work / "base", maps["base"]),
                RULE.POLICY.assess(
                    raw["candidate"], [], work / "candidate", maps["candidate"]
                ),
            )
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(len(result["introduced"]), 1)

    def test_paired_build_pins_keep_real_manifest_identity_on_rollout_base(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for side in ["base", "candidate"]:
                root = work / side
                root.mkdir()
                subprocess.run(["git", "init", "--quiet", str(root)], check=True)
                (root / "pyproject.toml").write_text(
                    '[build-system]\nrequires = ["setuptools==84.0.0"]\n'
                )
                subprocess.run(["git", "add", "pyproject.toml"], cwd=root, check=True)
            root = work / "candidate"
            (root / "ci").mkdir()
            (root / "ci/dependency-security-sources.json").write_text(
                '{"inherited_lockfiles": []}'
            )
            scanner = work / "scanner"
            scanner.write_text(f"""#!{sys.executable}
import json, pathlib, sys
results = []
for argument in sys.argv:
    if argument.startswith('--lockfile='):
        path = argument.split('=', 1)[1].removeprefix('osv-scanner:')
        entry = json.loads(pathlib.Path(path).read_text())['results'][0]['packages'][0]
        entry['vulnerabilities'] = [{{'id': {ADVISORY!r}}}]
        results.append({{'source': {{'path': path}}, 'packages': [entry]}})
output = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--output-file='))
pathlib.Path(output).write_text(json.dumps({{'results': results}}))
sys.exit(1)
""")
            scanner.chmod(0o755)
            temporary = work / "scan"
            temporary.mkdir()
            raw, maps, _ = RULE.paired_scan(root, work / "base", scanner, temporary)
            result = RULE.compare(
                RULE.POLICY.assess(raw["base"], [], work / "base", maps["base"]),
                RULE.POLICY.assess(raw["candidate"], [], root, maps["candidate"]),
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["retained"][0]["manifest"], "pyproject.toml")

    def test_real_cli_pairing_classification_and_errors(self):
        for old_ids, new_ids, scanner_exit, expected, status in [
            ([ADVISORY], [ADVISORY], 1, 0, "passed"),
            ([ADVISORY], [], 1, 0, "passed"),
            ([], [ADVISORY], 1, 1, "blocked"),
            ([ADVISORY], ["GHSA-aaaa-bbbb-cccc"], 1, 1, "blocked"),
            ([], [], 2, 2, "error"),
        ]:
            with (
                self.subTest(old=old_ids, new=new_ids, scanner_exit=scanner_exit),
                tempfile.TemporaryDirectory() as directory,
            ):
                work = Path(directory)
                for side, identifiers in [("base", old_ids), ("candidate", new_ids)]:
                    root = work / side
                    root.mkdir()
                    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
                    (root / "ci").mkdir()
                    (root / "ci/dependency-security-sources.json").write_text(
                        '{"inherited_lockfiles": []}'
                    )
                    (root / "ci/dependency-security-exceptions.json").write_text(
                        '{"schemaVersion": 1, "exceptions": []}'
                    )
                    data = {
                        "package": {
                            "name": "child",
                            "version": "1.0.0" if side == "base" else "1.0.1",
                            "ecosystem": "npm",
                        },
                        "vulnerabilities": [
                            {"id": identifier} for identifier in identifiers
                        ],
                    }
                    (root / "package-lock.json").write_text(json.dumps(data))
                    subprocess.run(
                        ["git", "add", "package-lock.json"], cwd=root, check=True
                    )
                scanner = work / "scanner"
                scanner.write_text(f"""#!{sys.executable}
import json, pathlib, sys
output = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--output-file='))
results = []
for value in sys.argv:
    if value.startswith('--lockfile='):
        path = value.split('=', 1)[1].removeprefix('osv-scanner:')
        results.append({{"source": {{"path": path}}, "packages": [json.loads(pathlib.Path(path).read_text())]}})
pathlib.Path(output).write_text(json.dumps({{"results": results}}))
with open({str(work / "calls")!r}, 'a') as calls: calls.write('scan\\n')
sys.exit({scanner_exit})
""")
                scanner.chmod(0o755)
                output = work / "assessment.json"
                command = [
                    sys.executable,
                    str(Path(RULE.__file__)),
                    "--root",
                    str(work / "candidate"),
                    "--base-root",
                    str(work / "base"),
                    "--scanner",
                    str(scanner),
                    "--report",
                    str(output),
                ]
                env = {
                    key: value
                    for key, value in os.environ.items()
                    if key != "GITHUB_STEP_SUMMARY"
                }
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                result = subprocess.run(
                    command, capture_output=True, text=True, env=env, check=False
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(json.loads(output.read_text())["status"], status)
                self.assertEqual((work / "calls").read_text().splitlines(), ["scan"])
                if scanner_exit != 2:
                    # The same command without a base is a full advisory report.
                    result = subprocess.run(
                        [
                            arg
                            for arg in command
                            if arg not in ["--base-root", str(work / "base")]
                        ],
                        capture_output=True,
                        text=True,
                        env=env,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        json.loads(output.read_text())["status"], "reported"
                    )

    def test_rollout_base_can_scan_inherited_inventory_without_policy_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            inherited = root / "lib/parent/uv.lock"
            inherited.parent.mkdir(parents=True)
            inherited.write_text("")
            files, _, _ = RULE.POLICY.inventory_files(
                root, root, ["lib/parent/uv.lock"]
            )
            self.assertEqual(files, [inherited])


if __name__ == "__main__":
    unittest.main()
