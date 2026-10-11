export type StoredIndexerIdentity = Readonly<{
    rawJournalVersion: string | null;
    dashboardProjectionVersion: string | null;
    stateSnapshotVersion: string | null;
    legacyIndexerVersion: string | null;
    dashboardProjectionGovernanceAddress: string | null;
    legacyGovernanceAddress: string | null;
}>;

export type ExpectedIndexerIdentity = Readonly<{
    rawJournalVersion: string;
    dashboardProjectionVersion: string;
    stateSnapshotVersion: string;
    governanceAddress: string;
}>;

export type IndexerIdentityTransition = Readonly<{
    initializeRawJournalIdentity: boolean;
    initializeStateSnapshotIdentity: boolean;
    resetProjection: boolean;
    resetStateSnapshots: boolean;
    restartScanFromDeployment: boolean;
}>;

export function planIndexerIdentityTransition(
    stored: StoredIndexerIdentity,
    expected: ExpectedIndexerIdentity
): IndexerIdentityTransition {
    if (
        stored.rawJournalVersion !== null &&
        stored.rawJournalVersion !== expected.rawJournalVersion
    ) {
        throw new Error(
            `Raw journal version ${stored.rawJournalVersion} is incompatible with ${expected.rawJournalVersion}`
        );
    }

    const effectiveProjectionVersion =
        stored.dashboardProjectionVersion ?? stored.legacyIndexerVersion;
    const effectiveGovernanceAddress =
        stored.dashboardProjectionGovernanceAddress ?? stored.legacyGovernanceAddress;
    const governanceChanged = effectiveGovernanceAddress !== expected.governanceAddress;

    return Object.freeze({
        initializeRawJournalIdentity: stored.rawJournalVersion === null,
        initializeStateSnapshotIdentity: stored.stateSnapshotVersion === null,
        resetProjection:
            effectiveProjectionVersion !== expected.dashboardProjectionVersion ||
            governanceChanged,
        resetStateSnapshots:
            stored.stateSnapshotVersion !== null &&
            stored.stateSnapshotVersion !== expected.stateSnapshotVersion,
        restartScanFromDeployment: governanceChanged,
    });
}
