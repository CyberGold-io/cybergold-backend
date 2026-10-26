#!/usr/bin/env python3
"""Regression tests for the common merge decision, independent of live advisories."""

import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "dependency_security", Path(__file__).with_name("check-dependency-security.py")
)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
ROOT = Path("/candidate")
ADVISORY = "GHSA-1234-5678-9abc"


def report(
    severity="LOW", advisory=ADVISORY, manifest="package-lock.json", package="child"
):
    return {
        "results": [
            {
                "source": {"path": str(ROOT / manifest), "type": "lockfile"},
                "packages": [
                    {
                        "package": {
                            "name": package,
                            "version": "1.0.0",
                            "ecosystem": "npm",
                        },
                        "vulnerabilities": [
                            {
                                "id": advisory,
                                "aliases": ["CVE-2026-12345"],
                                "database_specific": {"severity": severity},
                            }
                        ],
                    }
                ],
            }
        ]
    }


def exception():
    return {
        "advisory": ADVISORY,
        "ecosystem": "npm",
        "package": "child",
        "manifest": "package-lock.json",
        "reason": "Reviewed development-only exposure",
        "owner_approval": "Owner decision reference",
        "review_trigger": "Review when a parent release addresses this advisory",
    }


class DecisionTests(unittest.TestCase):
    def test_clean_inventory_passes(self):
        data = report()
        data["results"][0]["packages"][0]["vulnerabilities"] = []
        result = POLICY.assess(data, [], ROOT)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["packages_scanned"], 1)

    def test_every_severity_including_unknown_blocks(self):
        for severity in ("LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"):
            with self.subTest(severity=severity):
                result = POLICY.assess(report(severity), [], ROOT)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(len(result["blocking"]), 1)

    def test_exact_exception_is_visible_in_report(self):
        result = POLICY.assess(report(), [exception()], ROOT)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            result["accepted"][0]["exception"]["owner_approval"],
            "Owner decision reference",
        )

    def test_exception_does_not_accept_other_advisory_manifest_package_or_ecosystem(
        self,
    ):
        for key, value in (
            ("advisory", "GHSA-xxxx-yyyy-zzzz"),
            ("manifest", "other/package-lock.json"),
            ("package", "another-child"),
            ("ecosystem", "PyPI"),
        ):
            item = exception()
            item[key] = value
            with self.subTest(key=key):
                self.assertEqual(
                    POLICY.assess(report(), [item], ROOT)["status"], "blocked"
                )

    def test_new_advisory_in_same_package_still_blocks(self):
        data = report()
        data["results"][0]["packages"][0]["vulnerabilities"].append(
            {"id": "GHSA-aaaa-bbbb-cccc"}
        )
        result = POLICY.assess(data, [exception()], ROOT)
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(len(result["blocking"]), 1)

    def test_alias_matches_same_advisory_only(self):
        item = exception()
        item["advisory"] = "CVE-2026-12345"
        self.assertEqual(POLICY.assess(report(), [item], ROOT)["status"], "passed")

    def test_different_versions_remain_visible(self):
        data = report()
        second = copy.deepcopy(data["results"][0]["packages"][0])
        second["package"]["version"] = "1.0.1"
        data["results"][0]["packages"].append(second)
        self.assertEqual(len(POLICY.assess(data, [], ROOT)["blocking"]), 2)

    def test_build_pin_is_attributed_to_real_manifest(self):
        data = report(manifest="generated-build.json")
        result = POLICY.assess(
            data, [], ROOT, {str(ROOT / "generated-build.json"): "pyproject.toml"}
        )
        self.assertEqual(result["blocking"][0]["manifest"], "pyproject.toml")

    def test_malformed_scan_does_not_pass(self):
        for data in (
            {},
            {"results": None},
            {"results": [{"source": {"path": "uv.lock"}, "packages": None}]},
        ):
            with self.assertRaises((ValueError, TypeError)):
                POLICY.assess(data, [], ROOT)

    def test_wildcard_or_undocumented_exception_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exceptions.json"
            for change in (
                {"package": "*"},
                {"owner_approval": ""},
                {"reason": ""},
                {"review_trigger": ""},
            ):
                item = {**exception(), **change}
                path.write_text(json.dumps({"schemaVersion": 1, "exceptions": [item]}))
                with self.assertRaises(ValueError):
                    POLICY.load_exceptions(path)

    def test_build_dependency_is_included_without_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                '[build-system]\nrequires = ["setuptools==84.0.0"]\n'
            )
            (root / "ci").mkdir()
            (root / "ci/dependency-security-sources.json").write_text(
                '{"inherited_lockfiles": []}'
            )
            with (
                patch.object(POLICY, "tracked_files", return_value=["pyproject.toml"]),
                patch.object(POLICY.subprocess, "check_output", return_value=b""),
            ):
                files, sources, unresolved = POLICY.inventory_files(root, root)
            package = json.loads(files[0].read_text())["results"][0]["packages"][0][
                "package"
            ]
            self.assertEqual(package["version"], "84.0.0")
            self.assertEqual(unresolved, [])
            self.assertEqual(sources[str(files[0])], str(root / "pyproject.toml"))

    def test_scanner_error_cannot_be_reported_as_clean(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                POLICY, "inventory_files", return_value=([Path("uv.lock")], {}, [])
            ),
            patch.object(POLICY.subprocess, "run") as run,
        ):
            run.return_value.returncode = 2
            with self.assertRaisesRegex(RuntimeError, "exit code 2"):
                POLICY.run_scan(ROOT, Path("scanner"), Path(directory))

    def test_real_cli_distinguishes_clean_blocked_and_failed_scans(self):
        for scanner_exit, vulnerability, expected_exit, expected_status in (
            (0, False, 0, "passed"),
            (0, True, 1, "blocked"),
            (1, True, 1, "blocked"),
            (2, False, 2, "error"),
        ):
            with (
                self.subTest(scanner_exit=scanner_exit, vulnerability=vulnerability),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                subprocess.run(["git", "init", "--quiet", str(root)], check=True)
                (root / "ci").mkdir()
                (root / "ci/dependency-security-exceptions.json").write_text(
                    '{"schemaVersion": 1, "exceptions": []}'
                )
                (root / "ci/dependency-security-sources.json").write_text(
                    '{"inherited_lockfiles": []}'
                )
                (root / "package-lock.json").write_text("{}")
                subprocess.run(
                    ["git", "add", "package-lock.json"], cwd=root, check=True
                )
                data = report()
                data["results"][0]["source"]["path"] = str(root / "package-lock.json")
                if not vulnerability:
                    data["results"][0]["packages"][0]["vulnerabilities"] = []
                scanner = root / "scanner"
                scanner.write_text(
                    f"#!{sys.executable}\nimport json, pathlib, sys\n"
                    "output = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--output-file='))\n"
                    f"pathlib.Path(output).write_text({json.dumps(json.dumps(data))})\n"
                    f"sys.exit({scanner_exit})\n"
                )
                scanner.chmod(0o755)
                output = root / "assessment.json"
                result = subprocess.run(
                    [
                        sys.executable,
                        str(Path(POLICY.__file__)),
                        "--root",
                        str(root),
                        "--scanner",
                        str(scanner),
                        "--report",
                        str(output),
                    ],
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                self.assertEqual(
                    json.loads(output.read_text())["status"], expected_status
                )

    def test_download_checksum_mismatch_is_rejected(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(POLICY.tempfile, "gettempdir", return_value=directory),
            patch.object(POLICY.platform, "system", return_value="Linux"),
            patch.object(POLICY.platform, "machine", return_value="x86_64"),
            patch.object(
                POLICY.urllib.request,
                "urlopen",
                return_value=io.BytesIO(b"incorrect scanner bytes"),
            ),
            self.assertRaisesRegex(ValueError, "checksum mismatch"),
        ):
            POLICY.install_scanner()


if __name__ == "__main__":
    unittest.main()
