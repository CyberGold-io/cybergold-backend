#!/usr/bin/env node

import fs from "node:fs";
import process from "node:process";

const FEATURE_BRANCH = /^feature\/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$/;
const COMMIT_SHA = /^[a-f0-9]{40}$/;

function fail(message) {
  throw new Error(message);
}

function required(value, name) {
  if (typeof value !== "string" || value.length === 0) {
    fail(`${name} is required`);
  }
  return value;
}

function requireCommitSha(value, name) {
  required(value, name);
  if (!COMMIT_SHA.test(value)) {
    fail(`${name} must be a lowercase 40-character commit SHA`);
  }
  return value;
}

function requireFeatureBranch(value) {
  if (!FEATURE_BRANCH.test(value)) {
    fail("pull requests into dev must come from a lowercase feature/<slug> branch");
  }
}

export function validatePullRequest({ repository, headRepository, baseRef, headRef }) {
  required(repository, "repository");
  required(headRepository, "head repository");
  required(baseRef, "base ref");
  required(headRef, "head ref");

  if (baseRef === "main") {
    if (headRepository !== repository) {
      fail("main accepts pull requests only from the canonical repository; retarget fork contributions to dev");
    }
    if (headRef !== "dev") {
      fail("main accepts pull requests only from dev; retarget feature contributions to dev");
    }
    return;
  }
  if (baseRef === "dev") {
    requireFeatureBranch(headRef);
    return;
  }
  fail("Backend pull requests must target dev or main; retarget contributions to dev");
}

function readJson(path, description) {
  required(path, `${description} path`);
  const parsed = JSON.parse(fs.readFileSync(path, "utf8"));
  return parsed;
}

function matchingPullRequest(pr, { repository, refName, sha }) {
  if (!pr || typeof pr !== "object" || !pr.merged_at) return false;
  if (
    pr.base?.ref !== refName ||
    pr.base?.repo?.full_name !== repository
  ) {
    return false;
  }
  if (pr.merge_commit_sha !== sha) return false;
  if (refName === "main") {
    return pr.head?.repo?.full_name === repository && pr.head?.ref === "dev";
  }
  if (refName === "dev") return FEATURE_BRANCH.test(pr.head?.ref ?? "");
  return false;
}

function requireGitHubWebMergeProvenance(commit) {
  const gitCommit = commit.commit;
  const verification = gitCommit?.verification;
  const signature = verification?.signature;
  if (
    commit.committer?.login !== "web-flow" ||
    gitCommit?.committer?.name !== "GitHub" ||
    gitCommit?.committer?.email !== "noreply@github.com" ||
    verification?.verified !== true ||
    verification?.reason !== "valid" ||
    typeof signature !== "string" ||
    !signature.startsWith("-----BEGIN PGP SIGNATURE-----") ||
    !signature.trimEnd().endsWith("-----END PGP SIGNATURE-----")
  ) {
    fail("protected Backend publication requires a GitHub-web signed pull-request merge commit");
  }
}

export function validatePush({
  repository,
  refName,
  sha,
  beforeSha,
  forced,
  created,
  deleted,
  pullRequests,
  commit,
}) {
  required(repository, "repository");
  required(refName, "ref name");
  requireCommitSha(sha, "commit SHA");
  requireCommitSha(beforeSha, "prior branch SHA");
  if (refName !== "main" && refName !== "dev") {
    fail("push admission applies only to dev and main");
  }
  if (forced || created || deleted || /^0{40}$/.test(beforeSha)) {
    fail("protected Backend branch publication requires a non-forced update of an existing branch");
  }
  if (!Array.isArray(pullRequests)) {
    fail("associated pull-request response must be an array");
  }
  if (!commit || typeof commit !== "object" || commit.sha !== sha) {
    fail("pushed commit response does not match the triggering SHA");
  }
  requireGitHubWebMergeProvenance(commit);

  const parents = Array.isArray(commit.parents) ? commit.parents.map((value) => value.sha) : [];
  if (parents.length !== 2 || parents[0] !== beforeSha) {
    fail(
      `${refName} publication requires an ordered merge commit from the exact prior branch head and allowed pull-request head`,
    );
  }

  const matched = pullRequests.find(
    (pr) =>
      matchingPullRequest(pr, { repository, refName, sha }) &&
      pr.head?.sha === parents[1],
  );
  if (!matched) {
    fail(`push to ${refName} is not the merge result of an allowed pull request`);
  }
}

function envInput(name) {
  return required(process.env[name], name);
}

function booleanEnvInput(name) {
  const value = envInput(name);
  if (value === "true") return true;
  if (value === "false") return false;
  fail(`${name} must be true or false`);
}

function runPullRequest() {
  validatePullRequest({
    repository: envInput("BRANCH_POLICY_REPOSITORY"),
    headRepository: envInput("BRANCH_POLICY_HEAD_REPOSITORY"),
    baseRef: envInput("BRANCH_POLICY_BASE_REF"),
    headRef: envInput("BRANCH_POLICY_HEAD_REF"),
  });
  process.stdout.write("Backend pull-request branch policy passed.\n");
}

function runPush() {
  const pullRequests = readJson(
    envInput("BRANCH_POLICY_PULL_REQUESTS_FILE"),
    "associated pull-request response",
  );
  const commit = readJson(envInput("BRANCH_POLICY_COMMIT_FILE"), "commit response");
  validatePush({
    repository: envInput("BRANCH_POLICY_REPOSITORY"),
    refName: envInput("BRANCH_POLICY_REF_NAME"),
    sha: envInput("BRANCH_POLICY_SHA"),
    beforeSha: envInput("BRANCH_POLICY_BEFORE_SHA"),
    forced: booleanEnvInput("BRANCH_POLICY_FORCED"),
    created: booleanEnvInput("BRANCH_POLICY_CREATED"),
    deleted: booleanEnvInput("BRANCH_POLICY_DELETED"),
    pullRequests,
    commit,
  });
  process.stdout.write("Backend protected-branch push admission passed.\n");
}

function expectFailure(callback, description, expectedMessage = undefined) {
  try {
    callback();
  } catch (error) {
    if (
      expectedMessage !== undefined &&
      !(error instanceof Error && error.message.includes(expectedMessage))
    ) {
      fail(`negative fixture failed for the wrong reason (${description}): ${String(error)}`);
    }
    return;
  }
  fail(`negative fixture unexpectedly passed: ${description}`);
}

function selfTest() {
  const repository = "CyberGold-io/cybergold-backend";
  validatePullRequest({
    repository,
    headRepository: repository,
    baseRef: "dev",
    headRef: "feature/dapp-rpc-efficient-indexing-gateway",
  });
  validatePullRequest({
    repository,
    headRepository: repository,
    baseRef: "main",
    headRef: "dev",
  });
  expectFailure(
    () =>
      validatePullRequest({
        repository,
        headRepository: repository,
        baseRef: "main",
        headRef: "feature/bypass-dev",
      }),
    "feature branch targeting main",
  );
  const forkContribution = {
    repository,
    headRepository: "example/fork",
    baseRef: "dev",
    headRef: "feature/example",
  };
  validatePullRequest(forkContribution);
  expectFailure(
    () => validatePullRequest({ ...forkContribution, baseRef: "main" }),
    "fork feature retargeted to main",
    "main accepts pull requests only from the canonical repository",
  );
  // Re-evaluate the current target; a rejected main PR may be retargeted to dev.
  validatePullRequest({ ...forkContribution, baseRef: "dev" });
  expectFailure(
    () => validatePullRequest({ ...forkContribution, baseRef: "main", headRef: "dev" }),
    "fork branch named dev targeting main",
    "main accepts pull requests only from the canonical repository",
  );
  expectFailure(
    () => validatePullRequest({ ...forkContribution, headRef: "dev" }),
    "fork non-feature branch targeting dev",
    "lowercase feature/<slug>",
  );
  expectFailure(
    () => validatePullRequest({ ...forkContribution, baseRef: "release" }),
    "fork contribution targeting an unsupported branch",
    "pull requests must target dev or main",
  );

  const devSha = "d".repeat(40);
  const mainSha = "a".repeat(40);
  const baseSha = "b".repeat(40);
  const devPromotion = {
    merged_at: "2026-08-14T00:00:00Z",
    base: { ref: "main", repo: { full_name: repository } },
    head: { ref: "dev", sha: devSha, repo: { full_name: repository } },
    merge_commit_sha: mainSha,
  };
  const featureSha = "f".repeat(40);
  const featureMerge = {
    merged_at: "2026-08-14T00:00:00Z",
    base: { ref: "dev", repo: { full_name: repository } },
    head: {
      ref: "feature/dapp-rpc-efficient-indexing-gateway",
      sha: featureSha,
      repo: { full_name: repository },
    },
    merge_commit_sha: devSha,
  };
  const webMergeCommit = (sha, parents) => ({
    sha,
    parents: parents.map((parent) => ({ sha: parent })),
    committer: { login: "web-flow" },
    commit: {
      committer: { name: "GitHub", email: "noreply@github.com" },
      verification: {
        verified: true,
        reason: "valid",
        signature: "-----BEGIN PGP SIGNATURE-----\nfixture\n-----END PGP SIGNATURE-----",
      },
    },
  });
  const forkFeatureMerge = {
    ...featureMerge,
    head: { ...featureMerge.head, repo: { full_name: "example/fork" } },
  };
  const featurePush = (pullRequests) => ({
    repository,
    refName: "dev",
    sha: devSha,
    beforeSha: baseSha,
    forced: false,
    created: false,
    deleted: false,
    pullRequests,
    commit: webMergeCommit(devSha, [baseSha, featureSha]),
  });
  validatePush(featurePush([forkFeatureMerge]));
  for (const [description, invalidPullRequest] of [
    ["unmerged fork feature", { ...forkFeatureMerge, merged_at: null }],
    ["fork feature with a different merge SHA", { ...forkFeatureMerge, merge_commit_sha: mainSha }],
    ["fork feature with a different head SHA", {
      ...forkFeatureMerge, head: { ...forkFeatureMerge.head, sha: "e".repeat(40) },
    }],
    ["merged fork non-feature branch targeting dev", {
      ...forkFeatureMerge, head: { ...forkFeatureMerge.head, ref: "dev" },
    }],
    ["fork feature merged into a different base repository", {
      ...forkFeatureMerge, base: { ...forkFeatureMerge.base, repo: { full_name: "example/fork" } },
    }],
    ["fork feature sharing the head SHA but targeting main", {
      ...forkFeatureMerge, base: { ...forkFeatureMerge.base, ref: "main" },
    }],
  ]) {
    expectFailure(
      () => validatePush(featurePush([invalidPullRequest])),
      description,
      "push to dev is not the merge result of an allowed pull request",
    );
    validatePush(featurePush([invalidPullRequest, forkFeatureMerge]));
  }
  expectFailure(
    () => validatePush({
      ...featurePush([{
        ...devPromotion,
        head: { ...devPromotion.head, repo: { full_name: "example/fork" } },
      }]),
      refName: "main",
      sha: mainSha,
      commit: webMergeCommit(mainSha, [baseSha, devSha]),
    }),
    "merged fork branch named dev promoted to main",
    "push to main is not the merge result of an allowed pull request",
  );
  validatePush({
    repository,
    refName: "dev",
    sha: devSha,
    beforeSha: baseSha,
    forced: false,
    created: false,
    deleted: false,
    pullRequests: [featureMerge],
    commit: webMergeCommit(devSha, [baseSha, featureSha]),
  });
  const indirectlyAssociatedFeatureMerge = {
    ...featureMerge,
    head: {
      ...featureMerge.head,
      ref: "feature/indirectly-associated",
      sha: "e".repeat(40),
    },
  };
  validatePush({
    repository,
    refName: "dev",
    sha: devSha,
    beforeSha: baseSha,
    forced: false,
    created: false,
    deleted: false,
    pullRequests: [indirectlyAssociatedFeatureMerge, featureMerge],
    commit: webMergeCommit(devSha, [baseSha, featureSha]),
  });
  validatePush({
    repository,
    refName: "main",
    sha: mainSha,
    beforeSha: baseSha,
    forced: false,
    created: false,
    deleted: false,
    pullRequests: [devPromotion],
    commit: webMergeCommit(mainSha, [baseSha, devSha]),
  });
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "main",
        sha: mainSha,
        beforeSha: baseSha,
        forced: false,
        created: false,
        deleted: false,
        pullRequests: [devPromotion],
        commit: webMergeCommit(mainSha, [baseSha]),
      }),
    "squashed dev-to-main promotion",
  );
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "dev",
        sha: devSha,
        beforeSha: baseSha,
        forced: false,
        created: false,
        deleted: false,
        pullRequests: [],
        commit: webMergeCommit(devSha, [baseSha]),
      }),
    "direct dev push",
  );
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "dev",
        sha: devSha,
        beforeSha: baseSha,
        forced: false,
        created: false,
        deleted: false,
        pullRequests: [featureMerge],
        commit: webMergeCommit(devSha, [featureSha, baseSha]),
      }),
    "dev merge with reversed parents",
  );
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "main",
        sha: mainSha,
        beforeSha: "c".repeat(40),
        forced: false,
        created: false,
        deleted: false,
        pullRequests: [devPromotion],
        commit: webMergeCommit(mainSha, [baseSha, devSha]),
      }),
    "replay of an old valid main merge",
  );
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "dev",
        sha: devSha,
        beforeSha: baseSha,
        forced: true,
        created: false,
        deleted: false,
        pullRequests: [featureMerge],
        commit: webMergeCommit(devSha, [baseSha, featureSha]),
      }),
    "forced dev update",
    "non-forced update",
  );
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "dev",
        sha: devSha,
        beforeSha: baseSha,
        forced: false,
        created: true,
        deleted: false,
        pullRequests: [featureMerge],
        commit: webMergeCommit(devSha, [baseSha, featureSha]),
      }),
    "created dev branch",
    "non-forced update",
  );
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "dev",
        sha: devSha,
        beforeSha: baseSha,
        forced: false,
        created: false,
        deleted: true,
        pullRequests: [featureMerge],
        commit: webMergeCommit(devSha, [baseSha, featureSha]),
      }),
    "deleted dev branch",
    "non-forced update",
  );
  const unsignedManualMerge = webMergeCommit(devSha, [baseSha, featureSha]);
  unsignedManualMerge.committer = { login: "example-writer" };
  unsignedManualMerge.commit.verification = {
    verified: false,
    reason: "unsigned",
    signature: null,
  };
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "dev",
        sha: devSha,
        beforeSha: baseSha,
        forced: false,
        created: false,
        deleted: false,
        pullRequests: [featureMerge],
        commit: unsignedManualMerge,
      }),
    "manual merge pushed outside GitHub's pull-request merge path",
  );
  const nonPgpWebMerge = webMergeCommit(devSha, [baseSha, featureSha]);
  nonPgpWebMerge.commit.verification.signature =
    "-----BEGIN SSH SIGNATURE-----\nfixture\n-----END SSH SIGNATURE-----";
  expectFailure(
    () =>
      validatePush({
        repository,
        refName: "dev",
        sha: devSha,
        beforeSha: baseSha,
        forced: false,
        created: false,
        deleted: false,
        pullRequests: [featureMerge],
        commit: nonPgpWebMerge,
      }),
    "non-PGP signature with otherwise forged web-flow metadata",
    "GitHub-web signed",
  );
  process.stdout.write("Backend branch-policy fixtures passed.\n");
}

const mode = process.argv[2];
try {
  if (mode === "pull-request") runPullRequest();
  else if (mode === "push") runPush();
  else if (mode === "--self-test") selfTest();
  else fail("usage: check-branch-policy.mjs pull-request|push|--self-test");
} catch (error) {
  process.stderr.write(`ERROR: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
