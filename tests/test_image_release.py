from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "backend"
REPOSITORY = "CyberGold-io/cybergold-backend"
CI_FILE = "ci.yml"
COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
DIGEST = "sha256:" + "c" * 64

MOCK = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
cfg_path = pathlib.Path(os.environ['RELEASE_FIXTURE'])
cfg = json.loads(cfg_path.read_text())
with open(os.environ['RELEASE_LOG'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\n')
if name == 'gh':
    endpoint = args[1]
    if '/actions/runs/' in endpoint:
        run = dict(event='push',path='.github/workflows/'+cfg['ci'],status='completed',conclusion='success',head_branch=cfg['branch'],head_sha=cfg['commit'])
        run.update(cfg.get('run', {}))
        print(json.dumps(run))
    elif '/git/ref/' in endpoint:
        print('d'*40 if cfg.get('stale') else cfg['commit'])
    elif '/packages/' in endpoint:
        if cfg.get('missing_package'):
            print(json.dumps({'status':'404'}))
            sys.exit(1)
        print(json.dumps({'visibility':'private'}))
    else:
        raise SystemExit('Unexpected gh endpoint: '+endpoint)
elif name == 'node':
    print('e'*64)
elif args[:2] == ['image', 'inspect']:
    if cfg.get('missing_image'):
        sys.exit(1)
    labels = {'org.opencontainers.image.source':'https://github.com/'+cfg['repository'], 'org.opencontainers.image.revision':cfg['commit']}
    if '--format' in args:
        print(labels['org.opencontainers.image.revision'] if 'revision' in args[args.index('--format')+1] else cfg['image_id'])
    else:
        print(json.dumps([{'Id':cfg['image_id'],'Os':'linux','Architecture':'amd64','Config':{'Labels':labels}}]))
elif args[:2] == ['image', 'save']:
    pathlib.Path(args[args.index('--output')+1]).write_text('inert archive fixture')
elif args[0] == 'build':
    pathlib.Path(args[args.index('--iidfile')+1]).write_text(cfg['image_id'])
elif args[0] == 'login':
    assert sys.stdin.read() == 'fixture-credential'
    pathlib.Path(os.environ['DOCKER_CONFIG'], 'config.json').write_text('{}')
elif args[0] == 'push':
    tag = args[1].rsplit(':', 1)[1]
    if cfg.get('push_failure') and tag != 'desired':
        sys.exit(1)
    digest = 'd'*64 if tag == 'desired' and cfg.get('different_desired') else 'c'*64
    print('malformed push output' if cfg.get('malformed_push') else f'{tag}: digest: sha256:{digest} size: 100')
"""


@unittest.skipUnless(shutil.which("jq"), "jq is needed by the release scripts")
class ImageReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(
            ROOT / "scripts",
            self.root / "scripts",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("docker", "gh", "node"):
            tool = self.bin / name
            tool.write_text(MOCK)
            tool.chmod(0o755)
        self.fixture = self.root / "fixture.json"
        self.log = self.root / "calls.jsonl"
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "RELEASE_FIXTURE": str(self.fixture),
            "RELEASE_LOG": str(self.log),
            "RELEASE_SOURCE_BRANCH": "dev",
            "RELEASE_SOURCE_COMMIT": COMMIT,
            "RELEASE_CI_RUN_ID": "100",
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_RUN_ID": "200",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(self.root / "output"),
            "RUNNER_TEMP": str(self.root),
            "CONFIG_IMAGE_ID": IMAGE_ID,
            "GITHUB_ACTOR": "fixture",
            "GH_TOKEN": "fixture-read-token",
            "GHCR_TOKEN": "fixture-credential",
            "DOCKER_CONFIG": str(self.root / "docker-config"),
        }
        self.configure()

    def configure(self, **changes):
        cfg = {
            "ci": CI_FILE,
            "repository": REPOSITORY,
            "branch": self.env["RELEASE_SOURCE_BRANCH"],
            "commit": COMMIT,
            "image_id": IMAGE_ID,
        }
        cfg.update(changes)
        self.fixture.write_text(json.dumps(cfg))

    def execute(self, script, *args):
        return subprocess.run(
            ["bash", str(self.root / "scripts" / script), *args],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def calls(self):
        return (
            [json.loads(line) for line in self.log.read_text().splitlines()]
            if self.log.exists()
            else []
        )

    def publish(self, target="sandbox"):
        return self.execute(
            "publish-release-image.sh",
            target,
            str(self.root / "current-run.docker.tar"),
        )

    def assert_no_registry_access(self):
        self.assertFalse(
            any(
                call[0] == "docker" and call[1] in ("login", "push")
                for call in self.calls()
            )
        )

    def test_reuses_current_successful_push_authority(self):
        result = self.execute("require-image-release-authority.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "output").read_text(), "target=sandbox\n")

    def test_rejects_each_wrong_ci_identity_before_registry_access(self):
        cases = [
            ({"event": "pull_request"}, "push run"),
            ({"path": ".github/workflows/other.yml"}, "must use"),
            ({"status": "in_progress"}, "not completed"),
            ({"conclusion": "failure"}, "did not succeed"),
            ({"head_branch": "feature/untrusted"}, "wrong source branch"),
            ({"head_sha": "d" * 40}, "wrong source commit"),
        ]
        for run, message in cases:
            with self.subTest(run=run):
                self.configure(run=run)
                result = self.publish()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assert_no_registry_access()

    def test_stale_branch_head_cannot_publish(self):
        self.configure(stale=True)
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no longer the current mapped branch head", result.stderr)
        self.assert_no_registry_access()

    def test_missing_current_run_image_cannot_publish(self):
        self.configure(missing_image=True)
        self.assertNotEqual(self.publish().returncode, 0)
        self.assert_no_registry_access()

    def test_feature_branch_cannot_publish(self):
        self.env["RELEASE_SOURCE_BRANCH"] = "feature/source-owned-image-publication"
        self.configure()
        self.assertNotEqual(self.publish().returncode, 0)
        self.assert_no_registry_access()

    def test_immutable_image_precedes_desired_and_credentials_are_removed(self):
        targets = ("sandbox",) if COMPONENT == "safe" else ("sandbox", "mainnet")
        for target in targets:
            with self.subTest(target=target):
                self.env["RELEASE_SOURCE_BRANCH"] = (
                    "dev" if target == "sandbox" else "main"
                )
                self.configure()
                self.log.unlink(missing_ok=True)
                result = self.publish(target)
                self.assertEqual(result.returncode, 0, result.stderr)
                package = {
                    "backend": "cybergold-backend-b2b-" + target,
                    "safe": "cybergold-safe-tx-b2b-sandbox",
                    "broker": "cybergold-rpc-broker"
                    + ("-sandbox" if target == "sandbox" else ""),
                }[COMPONENT]
                repository = "ghcr.io/cybergold-io/" + package
                pushes = [
                    call[2] for call in self.calls() if call[:2] == ["docker", "push"]
                ]
                self.assertEqual(
                    pushes,
                    [
                        f"{repository}:{COMPONENT}-{COMMIT}-200-1",
                        f"{repository}:desired",
                    ],
                )
                evidence = json.loads(
                    (
                        self.root / f"out/ghcr-publication/{COMPONENT}-{target}.json"
                    ).read_text()
                )
                self.assertEqual(evidence["imageReference"], repository + "@" + DIGEST)
                self.assertEqual(evidence["sourceCommit"], COMMIT)
                self.assertEqual(evidence["sourceRepository"], REPOSITORY)
                self.assertFalse((self.root / "docker-config/config.json").exists())
                self.assertNotIn("fixture-credential", result.stdout + result.stderr)
                self.assertEqual(self.calls()[-1], ["docker", "logout", "ghcr.io"])
                self.assertFalse(
                    any(call[:2] == ["docker", "run"] for call in self.calls())
                )

    def test_failed_immutable_push_never_advances_desired(self):
        for changes in ({"push_failure": True}, {"malformed_push": True}):
            with self.subTest(changes=changes):
                self.configure(**changes)
                self.log.unlink(missing_ok=True)
                result = self.publish()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    any(call[-1].endswith(":desired") for call in self.calls())
                )
                self.assertFalse((self.root / "docker-config/config.json").exists())

    def test_different_desired_digest_is_reported(self):
        self.configure(different_desired=True)
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different manifest digest", result.stderr)

    def test_build_keeps_source_identity_and_emits_one_current_run_archive(self):
        result = self.execute("build-release-image.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        build = next(call for call in self.calls() if call[:2] == ["docker", "build"])
        self.assertIn("linux/amd64", build)
        self.assertIn("org.opencontainers.image.revision=" + COMMIT, build)
        self.assertIn(
            "org.opencontainers.image.source=https://github.com/" + REPOSITORY, build
        )
        archive_name = f"{COMPONENT}-image-200-1.docker.tar"
        self.assertTrue((self.root / archive_name).exists())
        output = (self.root / "output").read_text()
        self.assertIn("archive_name=" + archive_name, output)
        self.assertIn("config_image_id=" + IMAGE_ID, output)
        self.assert_no_registry_access()



if __name__ == "__main__":
    unittest.main()
