/** Plan a Sandbox projection transition after the Anvil process generation changes. */

const BLOCK_HASH = /^0x[0-9a-fA-F]{64}$/;

export type ForkGenerationAnchor = Readonly<{
  generation: string;
  forkBlock: bigint;
  forkBlockHash: string;
}>;

export type ForkGenerationPlan = Readonly<
  | { kind: "unchanged" }
  | {
      kind: "reuse-prefix";
      invalidateFrom: bigint;
      retainedThrough: bigint;
      retainedBlockHash: string;
    }
  | {
      kind: "replay-prefix";
      invalidateFrom: bigint;
      retainedThrough: bigint;
      retainedBlockHash: string;
    }
  | {
      kind: "full-replay";
      invalidateFrom: bigint;
      retainedThrough: null;
      retainedBlockHash: null;
    }
>;

/**
 * `currentHashAtPreviousForkBlock` must be read from the new Anvil generation.
 * A matching block at the previous fork point proves the retained prefix; a
 * missing or different hash requires replay from the deployment block.
 */
export function planForkGenerationTransition(input: {
  previous: ForkGenerationAnchor;
  current: ForkGenerationAnchor;
  deploymentStartBlock: bigint;
  currentHashAtPreviousForkBlock: string | null;
}): ForkGenerationPlan {
  const { previous, current, deploymentStartBlock } = input;
  for (const [label, anchor] of [["previous", previous], ["current", current]] as const) {
    if (!anchor.generation.trim()) throw new Error(`${label} fork generation is missing`);
    if (anchor.forkBlock < 0n) throw new Error(`${label} fork block is negative`);
    if (!BLOCK_HASH.test(anchor.forkBlockHash)) {
      throw new Error(`${label} fork block hash is invalid`);
    }
  }
  if (deploymentStartBlock < 0n) {
    throw new Error("deployment start block is negative");
  }
  if (deploymentStartBlock > current.forkBlock) {
    throw new Error("deployment start block is above the current fork point");
  }
  const oldHash = previous.forkBlockHash.toLowerCase();
  const newHash = current.forkBlockHash.toLowerCase();
  if (previous.generation === current.generation) {
    if (previous.forkBlock !== current.forkBlock || oldHash !== newHash) {
      throw new Error("fork history changed without a new process generation");
    }
    return { kind: "unchanged" };
  }
  if (
    current.forkBlock >= previous.forkBlock &&
    previous.forkBlock >= deploymentStartBlock &&
    input.currentHashAtPreviousForkBlock?.toLowerCase() === oldHash &&
    BLOCK_HASH.test(input.currentHashAtPreviousForkBlock)
  ) {
    return {
      kind: "reuse-prefix",
      invalidateFrom: previous.forkBlock + 1n,
      retainedThrough: previous.forkBlock,
      retainedBlockHash: oldHash,
    };
  }
  return {
    kind: "full-replay",
    invalidateFrom: deploymentStartBlock,
    retainedThrough: null,
    retainedBlockHash: null,
  };
}
