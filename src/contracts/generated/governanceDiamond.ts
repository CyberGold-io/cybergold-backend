// Generated from the compiled release facets. Do not edit by hand.
export const GOVERNANCE_DIAMOND_ABI = [
  {
    "type": "error",
    "name": "AccessControlBadConfirmation",
    "inputs": []
  },
  {
    "type": "error",
    "name": "AccessControlUnauthorizedAccount",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "neededRole",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "CannotAddFunctionToDiamondThatAlreadyExists",
    "inputs": [
      {
        "name": "_selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "CannotAddSelectorsToZeroAddress",
    "inputs": [
      {
        "name": "_selectors",
        "type": "bytes4[]",
        "internalType": "bytes4[]"
      }
    ]
  },
  {
    "type": "error",
    "name": "CannotRemoveFunctionThatDoesNotExist",
    "inputs": [
      {
        "name": "_selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "CannotRemoveImmutableFunction",
    "inputs": [
      {
        "name": "_selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "CannotReplaceFunctionThatDoesNotExists",
    "inputs": [
      {
        "name": "_selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "CannotReplaceFunctionWithTheSameFunctionFromTheSameFacet",
    "inputs": [
      {
        "name": "_selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "CannotReplaceFunctionsFromFacetWithZeroAddress",
    "inputs": [
      {
        "name": "_selectors",
        "type": "bytes4[]",
        "internalType": "bytes4[]"
      }
    ]
  },
  {
    "type": "error",
    "name": "CannotReplaceImmutableFunction",
    "inputs": [
      {
        "name": "_selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "CheckpointUnorderedInsertion",
    "inputs": []
  },
  {
    "type": "error",
    "name": "CriticalRoleLastUsableMember",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "CriticalRoleZeroAddress",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutCandidateFacetRuntimeMissing",
    "inputs": [
      {
        "name": "facet",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutCoordinatorImmutable",
    "inputs": [
      {
        "name": "selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutDuplicateFacetNamespace",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutFacetGenerationChangedDuringInitialization",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "expected",
        "type": "uint64",
        "internalType": "uint64"
      },
      {
        "name": "actual",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutFacetGenerationOverflow",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutFacetGenerationStateInvalid",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "generation",
        "type": "uint64",
        "internalType": "uint64"
      },
      {
        "name": "installed",
        "type": "bool",
        "internalType": "bool"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutFacetNamespaceChanged",
    "inputs": [
      {
        "name": "facet",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expectedNamespace",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "actualNamespace",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutFacetRuntimeChanged",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "facet",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expected",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "actual",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutFacetRuntimeUnchanged",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "incumbent",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "candidate",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "runtimeCodeHash",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutIncumbentFacetMetadataInvalid",
    "inputs": [
      {
        "name": "incumbent",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutIncumbentFacetRuntimeMissing",
    "inputs": [
      {
        "name": "incumbent",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutInitializerCalldataTooShort",
    "inputs": []
  },
  {
    "type": "error",
    "name": "DiamondCutInitializerRequired",
    "inputs": []
  },
  {
    "type": "error",
    "name": "DiamondCutInvalidFacetNamespace",
    "inputs": [
      {
        "name": "facet",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutPartialFacetNamespaceTransition",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "incumbent",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutRecoveryInvariantFailed",
    "inputs": [
      {
        "name": "selector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutReentrancy",
    "inputs": []
  },
  {
    "type": "error",
    "name": "DiamondCutSelectorCountMismatch",
    "inputs": [
      {
        "name": "expected",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutSelectorEnumerationMismatch",
    "inputs": [
      {
        "name": "selector",
        "type": "bytes4",
        "internalType": "bytes4"
      },
      {
        "name": "recordedPosition",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "enumeratedSelector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutSelectorOwnerMismatch",
    "inputs": [
      {
        "name": "selector",
        "type": "bytes4",
        "internalType": "bytes4"
      },
      {
        "name": "expected",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "actual",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutUnexpectedInitializerCalldata",
    "inputs": []
  },
  {
    "type": "error",
    "name": "ECDSAInvalidSignature",
    "inputs": []
  },
  {
    "type": "error",
    "name": "ECDSAInvalidSignatureLength",
    "inputs": [
      {
        "name": "length",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ECDSAInvalidSignatureS",
    "inputs": [
      {
        "name": "s",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC20ExceededSafeSupply",
    "inputs": [
      {
        "name": "increasedSupply",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "cap",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC20InsufficientAllowance",
    "inputs": [
      {
        "name": "spender",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "allowance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "needed",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC20InsufficientBalance",
    "inputs": [
      {
        "name": "sender",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "balance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "needed",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC20InvalidApprover",
    "inputs": [
      {
        "name": "approver",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC20InvalidReceiver",
    "inputs": [
      {
        "name": "receiver",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC20InvalidSender",
    "inputs": [
      {
        "name": "sender",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC20InvalidSpender",
    "inputs": [
      {
        "name": "spender",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC2612ExpiredSignature",
    "inputs": [
      {
        "name": "deadline",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC2612InvalidSigner",
    "inputs": [
      {
        "name": "signer",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC5805FutureLookup",
    "inputs": [
      {
        "name": "timepoint",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "clock",
        "type": "uint48",
        "internalType": "uint48"
      }
    ]
  },
  {
    "type": "error",
    "name": "EmergencyAuthorityUnauthorizedAccount",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "EnforcedPause",
    "inputs": []
  },
  {
    "type": "error",
    "name": "ExpectedPause",
    "inputs": []
  },
  {
    "type": "error",
    "name": "FacetGenerationAlreadyInitialized",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "current",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "FacetInitCallerNotSelf",
    "inputs": [
      {
        "name": "caller",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "FacetLaunchNamespaceInvalid",
    "inputs": [
      {
        "name": "target",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "FacetNamespaceProbeFailed",
    "inputs": [
      {
        "name": "target",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "FacetRuntimeNotInstalled",
    "inputs": [
      {
        "name": "target",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "FailedCall",
    "inputs": []
  },
  {
    "type": "error",
    "name": "GovernanceTreasuryDelegationForbidden",
    "inputs": [
      {
        "name": "delegatee",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorAlreadyCastVote",
    "inputs": [
      {
        "name": "voter",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorDisabledDeposit",
    "inputs": []
  },
  {
    "type": "error",
    "name": "GovernorExecutionPolicyInvalid",
    "inputs": [
      {
        "name": "executionDelay",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "executionGracePeriod",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorExternalSupplyZero",
    "inputs": []
  },
  {
    "type": "error",
    "name": "GovernorInsufficientProposerVotes",
    "inputs": [
      {
        "name": "proposer",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "votes",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "threshold",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidExecutionDelay",
    "inputs": [
      {
        "name": "requested",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "minimum",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "maximum",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidExecutionGracePeriod",
    "inputs": [
      {
        "name": "requested",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "minimum",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "maximum",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidProposalLength",
    "inputs": [
      {
        "name": "targets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "calldatas",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "values",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidProposalThresholdNumerator",
    "inputs": [
      {
        "name": "requested",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "minimum",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "maximum",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidQuorumNumerator",
    "inputs": [
      {
        "name": "requested",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "minimum",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "maximum",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidSignature",
    "inputs": [
      {
        "name": "voter",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidTreasuryBalance",
    "inputs": [
      {
        "name": "totalSupply",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "treasuryBalance",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidVoteParams",
    "inputs": []
  },
  {
    "type": "error",
    "name": "GovernorInvalidVoteType",
    "inputs": []
  },
  {
    "type": "error",
    "name": "GovernorInvalidVotingDelay",
    "inputs": [
      {
        "name": "requested",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "minimum",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "maximum",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorInvalidVotingPeriod",
    "inputs": [
      {
        "name": "votingPeriod",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorNonexistentProposal",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorNonzeroProposalValue",
    "inputs": [
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorOnlyExecutor",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorPolicyChangeNoop",
    "inputs": []
  },
  {
    "type": "error",
    "name": "GovernorPolicyCurrentMismatch",
    "inputs": [
      {
        "name": "expected",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorProposalExecutionWindowInvalid",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "readyAt",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "expiresAt",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorProposalExecutionWindowUnset",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorProposalExpired",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "expiresAt",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorProposalNotReady",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "readyAt",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorProposalQuorumAlreadySet",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorProposalQuorumUnset",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorProposalVotingPolicyInvalid",
    "inputs": [
      {
        "name": "proposalThresholdNumerator",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "quorumNumerator",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorRestrictedProposer",
    "inputs": [
      {
        "name": "proposer",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorTimepointQuorumUnsupported",
    "inputs": []
  },
  {
    "type": "error",
    "name": "GovernorUnableToCancel",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorUnexpectedMsgValue",
    "inputs": [
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorUnexpectedProposalState",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "current",
        "type": "uint8",
        "internalType": "enum IGovernor.ProposalState"
      },
      {
        "name": "expectedStates",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "GovernorVotingPeriodOutOfBounds",
    "inputs": [
      {
        "name": "requested",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "minimum",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "maximum",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "IncorrectFacetCutAction",
    "inputs": [
      {
        "name": "_action",
        "type": "uint8",
        "internalType": "uint8"
      }
    ]
  },
  {
    "type": "error",
    "name": "InitialHolderRequired",
    "inputs": []
  },
  {
    "type": "error",
    "name": "InitializationFunctionReverted",
    "inputs": [
      {
        "name": "_initializationContractAddress",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "_calldata",
        "type": "bytes",
        "internalType": "bytes"
      }
    ]
  },
  {
    "type": "error",
    "name": "InvalidAccountNonce",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "currentNonce",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "InvalidInitialization",
    "inputs": []
  },
  {
    "type": "error",
    "name": "InvalidSafeWallet",
    "inputs": [
      {
        "name": "candidate",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "NoBytecodeAtAddress",
    "inputs": [
      {
        "name": "_contractAddress",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "_message",
        "type": "string",
        "internalType": "string"
      }
    ]
  },
  {
    "type": "error",
    "name": "NoSelectorsProvidedForFacetForCut",
    "inputs": [
      {
        "name": "_facetAddress",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "NotInitializing",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundAllowanceAccountingInvalid",
    "inputs": [
      {
        "name": "balance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "allowanceExposure",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundAllowanceExposureProbeFailed",
    "inputs": [
      {
        "name": "core",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundAllowancePostStateMismatch",
    "inputs": [
      {
        "name": "spender",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "supplied",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "observed",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundAllowanceProbeFailed",
    "inputs": [
      {
        "name": "core",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "spender",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundCallbackMalformed",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundCapacityExceeded",
    "inputs": [
      {
        "name": "requested",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "remaining",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundCommitmentExceedsReference",
    "inputs": [
      {
        "name": "commitment",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "coverageShares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "referenceShares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "referenceValueCygld",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundCommitmentZero",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundCoreMutationDuringPurchase",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundCoverageMismatch",
    "inputs": [
      {
        "name": "expected",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundCygldCommitmentDeficit",
    "inputs": [
      {
        "name": "balance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "allowanceExposure",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "committed",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundCygldPostStateMismatch",
    "inputs": [
      {
        "name": "suppliedBalance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "observedBalance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "suppliedExposure",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "observedExposure",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundExactCreditMismatch",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expected",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundExactDebitMismatch",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expected",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundFacilityAlreadyActive",
    "inputs": [
      {
        "name": "impairedAsset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "generation",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundFacilityInactive",
    "inputs": [
      {
        "name": "impairedAsset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "generation",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundGenerationExhausted",
    "inputs": [
      {
        "name": "generation",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundGenerationMismatch",
    "inputs": [
      {
        "name": "expected",
        "type": "uint64",
        "internalType": "uint64"
      },
      {
        "name": "actual",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundGovernanceBalanceExceedsExternalShares",
    "inputs": [
      {
        "name": "governanceBalance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "externalShares",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundInvalidShareId",
    "inputs": [
      {
        "name": "shareId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundMinimumNotMet",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "minimum",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundOperatorInvalid",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "seller",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundPayoutZero",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundPoolAccountingMismatch",
    "inputs": [
      {
        "name": "expected",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundPurchaseAmountZero",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundRecoveryShareOutflowForbidden",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "recipient",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundRedemptionAmountZero",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundRedemptionRecipientInvalid",
    "inputs": [
      {
        "name": "recipient",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundReferenceUnavailable",
    "inputs": [
      {
        "name": "referenceShares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "referenceValueCygld",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundShareBalanceMismatch",
    "inputs": [
      {
        "name": "expected",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundShareBalanceProbeFailed",
    "inputs": [
      {
        "name": "core",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shareId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundTokenBalanceProbeFailed",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundTrustedCoreBatchRejected",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundTrustedCoreCallbackOnly",
    "inputs": [
      {
        "name": "caller",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundTrustedCoreInvalid",
    "inputs": [
      {
        "name": "core",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundUnauthorizedSelfCall",
    "inputs": [
      {
        "name": "caller",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryFundZeroAddress",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RecoveryFundZeroCoverage",
    "inputs": []
  },
  {
    "type": "error",
    "name": "ReentrancyGuardReentrantCall",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RemoveFacetAddressMustBeZeroAddress",
    "inputs": [
      {
        "name": "_facetAddress",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "SafeCastOverflowedUintDowncast",
    "inputs": [
      {
        "name": "bits",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "SafeERC20FailedOperation",
    "inputs": [
      {
        "name": "token",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "SafeWalletExpectedCurrentMismatch",
    "inputs": [
      {
        "name": "expected",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "actual",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "SafeWalletUnchanged",
    "inputs": [
      {
        "name": "safeWallet",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "VotesExpiredSignature",
    "inputs": [
      {
        "name": "expiry",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ZeroAddress",
    "inputs": []
  },
  {
    "type": "event",
    "name": "Approval",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "spender",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "value",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "AssetRecoveryFundActivated",
    "inputs": [
      {
        "name": "impairedAsset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "generation",
        "type": "uint64",
        "indexed": true,
        "internalType": "uint64"
      },
      {
        "name": "coverageShares",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "cygldCommitment",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "DelegateChanged",
    "inputs": [
      {
        "name": "delegator",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "fromDelegate",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "toDelegate",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "DelegateVotesChanged",
    "inputs": [
      {
        "name": "delegate",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "previousVotes",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newVotes",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "DiamondCut",
    "inputs": [
      {
        "name": "_diamondCut",
        "type": "tuple[]",
        "indexed": false,
        "internalType": "struct IDiamond.FacetCut[]",
        "components": [
          {
            "name": "facetAddress",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "action",
            "type": "uint8",
            "internalType": "enum IDiamond.FacetCutAction"
          },
          {
            "name": "functionSelectors",
            "type": "bytes4[]",
            "internalType": "bytes4[]"
          }
        ]
      },
      {
        "name": "_init",
        "type": "address",
        "indexed": false,
        "internalType": "address"
      },
      {
        "name": "_calldata",
        "type": "bytes",
        "indexed": false,
        "internalType": "bytes"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "EIP712DomainChanged",
    "inputs": [],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ExecutionDelaySet",
    "inputs": [
      {
        "name": "oldExecutionDelay",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newExecutionDelay",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ExecutionGracePeriodSet",
    "inputs": [
      {
        "name": "oldExecutionGracePeriod",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newExecutionGracePeriod",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "FacetGenerationUpdated",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "indexed": true,
        "internalType": "bytes32"
      },
      {
        "name": "incumbent",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "candidate",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "oldRuntimeCodeHash",
        "type": "bytes32",
        "indexed": false,
        "internalType": "bytes32"
      },
      {
        "name": "newRuntimeCodeHash",
        "type": "bytes32",
        "indexed": false,
        "internalType": "bytes32"
      },
      {
        "name": "resultingGeneration",
        "type": "uint64",
        "indexed": false,
        "internalType": "uint64"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "Initialized",
    "inputs": [
      {
        "name": "version",
        "type": "uint64",
        "indexed": false,
        "internalType": "uint64"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "Paused",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "indexed": false,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ProposalCanceled",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ProposalCreated",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "proposer",
        "type": "address",
        "indexed": false,
        "internalType": "address"
      },
      {
        "name": "targets",
        "type": "address[]",
        "indexed": false,
        "internalType": "address[]"
      },
      {
        "name": "values",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      },
      {
        "name": "signatures",
        "type": "string[]",
        "indexed": false,
        "internalType": "string[]"
      },
      {
        "name": "calldatas",
        "type": "bytes[]",
        "indexed": false,
        "internalType": "bytes[]"
      },
      {
        "name": "voteStart",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "voteEnd",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "description",
        "type": "string",
        "indexed": false,
        "internalType": "string"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ProposalExecuted",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ProposalExecutionWindowCreated",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "indexed": true,
        "internalType": "uint256"
      },
      {
        "name": "readyAt",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "expiresAt",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "executionDelay",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "executionGracePeriod",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ProposalThresholdNumeratorSet",
    "inputs": [
      {
        "name": "oldNumerator",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newNumerator",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "QuorumNumeratorSet",
    "inputs": [
      {
        "name": "oldQuorumNumerator",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newQuorumNumerator",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RecoveryFundInitialized",
    "inputs": [
      {
        "name": "trustedCore",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RecoverySharesPurchased",
    "inputs": [
      {
        "name": "impairedAsset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "generation",
        "type": "uint64",
        "indexed": true,
        "internalType": "uint64"
      },
      {
        "name": "seller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "cygldAmount",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RoleAdminChanged",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "indexed": true,
        "internalType": "bytes32"
      },
      {
        "name": "previousAdminRole",
        "type": "bytes32",
        "indexed": true,
        "internalType": "bytes32"
      },
      {
        "name": "newAdminRole",
        "type": "bytes32",
        "indexed": true,
        "internalType": "bytes32"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RoleGranted",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "indexed": true,
        "internalType": "bytes32"
      },
      {
        "name": "account",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "sender",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RoleRevoked",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "indexed": true,
        "internalType": "bytes32"
      },
      {
        "name": "account",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "sender",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "SafeWalletUpdated",
    "inputs": [
      {
        "name": "previousSafeWallet",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "newSafeWallet",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "Transfer",
    "inputs": [
      {
        "name": "from",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "to",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "value",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "TreasuryWithdrawn",
    "inputs": [
      {
        "name": "token",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "to",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "amount",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "Unpaused",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "indexed": false,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ValidatedDiamondCutExecuted",
    "inputs": [
      {
        "name": "upgradeHash",
        "type": "bytes32",
        "indexed": true,
        "internalType": "bytes32"
      },
      {
        "name": "initializer",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "initializerCodeHash",
        "type": "bytes32",
        "indexed": false,
        "internalType": "bytes32"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "VoteCast",
    "inputs": [
      {
        "name": "voter",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "proposalId",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "support",
        "type": "uint8",
        "indexed": false,
        "internalType": "uint8"
      },
      {
        "name": "weight",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "reason",
        "type": "string",
        "indexed": false,
        "internalType": "string"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "VoteCastWithParams",
    "inputs": [
      {
        "name": "voter",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "proposalId",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "support",
        "type": "uint8",
        "indexed": false,
        "internalType": "uint8"
      },
      {
        "name": "weight",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "reason",
        "type": "string",
        "indexed": false,
        "internalType": "string"
      },
      {
        "name": "params",
        "type": "bytes",
        "indexed": false,
        "internalType": "bytes"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "VotingDelaySet",
    "inputs": [
      {
        "name": "oldVotingDelay",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newVotingDelay",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "VotingPeriodSet",
    "inputs": [
      {
        "name": "oldVotingPeriod",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newVotingPeriod",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "function",
    "name": "BALLOT_TYPEHASH",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "CLOCK_MODE",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "string",
        "internalType": "string"
      }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "COUNTING_MODE",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "string",
        "internalType": "string"
      }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "DEFAULT_ADMIN_ROLE",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "DOMAIN_SEPARATOR",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "acquiredRecoveryShares",
    "inputs": [
      {
        "name": "impairedAsset",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "activateAssetRecoveryFund",
    "inputs": [
      {
        "name": "request",
        "type": "tuple",
        "internalType": "struct IRecoveryFundTypes.AssetRecoveryFundActivation",
        "components": [
          {
            "name": "impairedAsset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "expectedNextGeneration",
            "type": "uint64",
            "internalType": "uint64"
          },
          {
            "name": "expectedCoverageShares",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "cygldCommitment",
            "type": "uint256",
            "internalType": "uint256"
          }
        ]
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "allowance",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "spender",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "approve",
    "inputs": [
      {
        "name": "spender",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "assetRecoveryFund",
    "inputs": [
      {
        "name": "impairedAsset",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "viewData",
        "type": "tuple",
        "internalType": "struct IRecoveryFundTypes.AssetRecoveryFundView",
        "components": [
          {
            "name": "generation",
            "type": "uint64",
            "internalType": "uint64"
          },
          {
            "name": "coverageShares",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "purchasedShares",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "initialCygldCommitment",
            "type": "uint256",
            "internalType": "uint256"
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "balanceOf",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "canPause",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "canUnpause",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "cancel",
    "inputs": [
      {
        "name": "targets",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "values",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "calldatas",
        "type": "bytes[]",
        "internalType": "bytes[]"
      },
      {
        "name": "descriptionHash",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "castVote",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "support",
        "type": "uint8",
        "internalType": "uint8"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "castVoteBySig",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "support",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "voter",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "signature",
        "type": "bytes",
        "internalType": "bytes"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "castVoteWithReason",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "support",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "reason",
        "type": "string",
        "internalType": "string"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "checkpoints",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "pos",
        "type": "uint32",
        "internalType": "uint32"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "tuple",
        "internalType": "struct Checkpoints.Checkpoint208",
        "components": [
          {
            "name": "_key",
            "type": "uint48",
            "internalType": "uint48"
          },
          {
            "name": "_value",
            "type": "uint208",
            "internalType": "uint208"
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "clock",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint48",
        "internalType": "uint48"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "decimals",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint8",
        "internalType": "uint8"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "delegate",
    "inputs": [
      {
        "name": "delegatee",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "delegateBySig",
    "inputs": [
      {
        "name": "delegatee",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "nonce",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "expiry",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "v",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "r",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "s",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "delegates",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "diamondCut",
    "inputs": [
      {
        "name": "_diamondCut",
        "type": "tuple[]",
        "internalType": "struct IDiamond.FacetCut[]",
        "components": [
          {
            "name": "facetAddress",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "action",
            "type": "uint8",
            "internalType": "enum IDiamond.FacetCutAction"
          },
          {
            "name": "functionSelectors",
            "type": "bytes4[]",
            "internalType": "bytes4[]"
          }
        ]
      },
      {
        "name": "_init",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "_calldata",
        "type": "bytes",
        "internalType": "bytes"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "eip712Domain",
    "inputs": [],
    "outputs": [
      {
        "name": "fields",
        "type": "bytes1",
        "internalType": "bytes1"
      },
      {
        "name": "name",
        "type": "string",
        "internalType": "string"
      },
      {
        "name": "version",
        "type": "string",
        "internalType": "string"
      },
      {
        "name": "chainId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "verifyingContract",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "salt",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "extensions",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "execute",
    "inputs": [
      {
        "name": "targets",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "values",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "calldatas",
        "type": "bytes[]",
        "internalType": "bytes[]"
      },
      {
        "name": "descriptionHash",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "executionDelay",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "executionGracePeriod",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "externalCygovSupply",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "facetAddress",
    "inputs": [
      {
        "name": "functionSelector",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "outputs": [
      {
        "name": "facetAddress_",
        "type": "address",
        "internalType": "address"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "facetAddresses",
    "inputs": [],
    "outputs": [
      {
        "name": "facetAddresses_",
        "type": "address[]",
        "internalType": "address[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "facetFunctionSelectors",
    "inputs": [
      {
        "name": "facet",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "facetFunctionSelectors_",
        "type": "bytes4[]",
        "internalType": "bytes4[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "facetGeneration",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [
      {
        "name": "generation",
        "type": "uint64",
        "internalType": "uint64"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "facets",
    "inputs": [],
    "outputs": [
      {
        "name": "facets_",
        "type": "tuple[]",
        "internalType": "struct IDiamondLoupe.Facet[]",
        "components": [
          {
            "name": "facetAddress",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "functionSelectors",
            "type": "bytes4[]",
            "internalType": "bytes4[]"
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getPastTotalSupply",
    "inputs": [
      {
        "name": "timepoint",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getPastVotes",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "timepoint",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getProposalId",
    "inputs": [
      {
        "name": "targets",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "values",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "calldatas",
        "type": "bytes[]",
        "internalType": "bytes[]"
      },
      {
        "name": "descriptionHash",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getRoleAdmin",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getRoleMember",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getRoleMemberCount",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getRoleMembers",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "address[]",
        "internalType": "address[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getVotes",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "getVotes",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "timepoint",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "grantRole",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "hasRole",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "hasVoted",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "hashProposal",
    "inputs": [
      {
        "name": "targets",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "values",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "calldatas",
        "type": "bytes[]",
        "internalType": "bytes[]"
      },
      {
        "name": "descriptionHash",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "name",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "string",
        "internalType": "string"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "nonces",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "numCheckpoints",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint32",
        "internalType": "uint32"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "onCygldApprovalChange",
    "inputs": [
      {
        "name": "spender",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "previousAllowance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "newAllowance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "balanceAfter",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "allowanceExposureAfter",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "onCygldOutflow",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "recipient",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "amount",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "balanceAfter",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "allowanceExposureAfter",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "magic",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "onERC1155BatchReceived",
    "inputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "",
        "type": "bytes",
        "internalType": "bytes"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "onERC1155Received",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "from",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "id",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "data",
        "type": "bytes",
        "internalType": "bytes"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "onERC721Received",
    "inputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "",
        "type": "bytes",
        "internalType": "bytes"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "onRecoveryShareOutflow",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "recipient",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shareIds",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "amounts",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "onRecoveryShareRedemption",
    "inputs": [
      {
        "name": "impairedAsset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "recipient",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "minRawOut",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "rawOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "pause",
    "inputs": [],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "paused",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "permit",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "spender",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "deadline",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "v",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "r",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "s",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "previewAssetRecoveryFundPurchase",
    "inputs": [
      {
        "name": "impairedAsset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "generation",
        "type": "uint64",
        "internalType": "uint64"
      },
      {
        "name": "cygldOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalDeadline",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalEta",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalExpiresAt",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalNeedsQueuing",
    "inputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "proposalProposer",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalQuorum",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalSnapshot",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalThreshold",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalThresholdNumerator",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "proposalVotes",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "againstVotes",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "forVotes",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "abstainVotes",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "propose",
    "inputs": [
      {
        "name": "targets",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "values",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "calldatas",
        "type": "bytes[]",
        "internalType": "bytes[]"
      },
      {
        "name": "description",
        "type": "string",
        "internalType": "string"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "quorumNumerator",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "recoveryFundTreasuryStatus",
    "inputs": [],
    "outputs": [
      {
        "name": "balance",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "allowanceExposure",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "committed",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "renounceRole",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "callerConfirmation",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "revokeRole",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "safeWallet",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "setExecutionDelay",
    "inputs": [
      {
        "name": "currentExecutionDelay",
        "type": "uint48",
        "internalType": "uint48"
      },
      {
        "name": "newExecutionDelay",
        "type": "uint48",
        "internalType": "uint48"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setExecutionGracePeriod",
    "inputs": [
      {
        "name": "currentExecutionGracePeriod",
        "type": "uint48",
        "internalType": "uint48"
      },
      {
        "name": "newExecutionGracePeriod",
        "type": "uint48",
        "internalType": "uint48"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setProposalThresholdNumerator",
    "inputs": [
      {
        "name": "currentNumerator",
        "type": "uint32",
        "internalType": "uint32"
      },
      {
        "name": "newNumerator",
        "type": "uint32",
        "internalType": "uint32"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setQuorumNumerator",
    "inputs": [
      {
        "name": "currentQuorumNumerator",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "newQuorumNumerator",
        "type": "uint8",
        "internalType": "uint8"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setSafeWallet",
    "inputs": [
      {
        "name": "expectedCurrentSafeWallet",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "newSafeWallet",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setVotingDelay",
    "inputs": [
      {
        "name": "currentVotingDelay",
        "type": "uint48",
        "internalType": "uint48"
      },
      {
        "name": "newVotingDelay",
        "type": "uint48",
        "internalType": "uint48"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setVotingPeriod",
    "inputs": [
      {
        "name": "currentVotingPeriod",
        "type": "uint32",
        "internalType": "uint32"
      },
      {
        "name": "newVotingPeriod",
        "type": "uint32",
        "internalType": "uint32"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "state",
    "inputs": [
      {
        "name": "proposalId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint8",
        "internalType": "enum IGovernor.ProposalState"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "supportsInterface",
    "inputs": [
      {
        "name": "interfaceId",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "symbol",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "string",
        "internalType": "string"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "token",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "contract IERC5805"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "totalSupply",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "transfer",
    "inputs": [
      {
        "name": "to",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "transferFrom",
    "inputs": [
      {
        "name": "from",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "to",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "treasuryWithdraw",
    "inputs": [
      {
        "name": "token",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "to",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "amount",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "trustedRecoveryFundCore",
    "inputs": [],
    "outputs": [
      {
        "name": "core",
        "type": "address",
        "internalType": "address"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "unpause",
    "inputs": [],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "upgraderRole",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "version",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "string",
        "internalType": "string"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "votingDelay",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "votingPeriod",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  }
] as const;

export const GOVERNANCE_DIAMOND_FUNCTIONS = [
  {
    "selector": "0x001f229b",
    "signature": "recoveryFundTreasuryStatus()",
    "facet": "recoveryFundLens",
    "scope": "product"
  },
  {
    "selector": "0x01ffc9a7",
    "signature": "supportsInterface(bytes4)",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0x02a251a3",
    "signature": "votingPeriod()",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0x06fdde03",
    "signature": "name()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x07389841",
    "signature": "upgraderRole()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x095ea7b3",
    "signature": "approve(address,uint256)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x0d11c635",
    "signature": "facetGeneration(bytes32)",
    "facet": "cut",
    "scope": "base"
  },
  {
    "selector": "0x0f00c179",
    "signature": "setVotingPeriod(uint32,uint32)",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0x143489d0",
    "signature": "proposalProposer(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x146d838b",
    "signature": "externalCygovSupply()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x150b7a02",
    "signature": "onERC721Received(address,address,uint256,bytes)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x18160ddd",
    "signature": "totalSupply()",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x1f931c1c",
    "signature": "diamondCut((address,uint8,bytes4[])[],address,bytes)",
    "facet": "cut",
    "scope": "base"
  },
  {
    "selector": "0x23b872dd",
    "signature": "transferFrom(address,address,uint256)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x248a9ca3",
    "signature": "getRoleAdmin(bytes32)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x2656227d",
    "signature": "execute(address[],uint256[],bytes[],bytes32)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x2d63f693",
    "signature": "proposalSnapshot(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x2f2ff15d",
    "signature": "grantRole(bytes32,address)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x313ce567",
    "signature": "decimals()",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x327a71e7",
    "signature": "proposalThresholdNumerator()",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0x3644e515",
    "signature": "DOMAIN_SEPARATOR()",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x36568abe",
    "signature": "renounceRole(bytes32,address)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x3932abb1",
    "signature": "votingDelay()",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0x3a46b1a8",
    "signature": "getPastVotes(address,uint256)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x3e35db1e",
    "signature": "activateAssetRecoveryFund((address,uint64,uint256,uint256))",
    "facet": "recoveryFund",
    "scope": "product"
  },
  {
    "selector": "0x3e4f49e6",
    "signature": "state(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x3f4ba83a",
    "signature": "unpause()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x43859632",
    "signature": "hasVoted(uint256,address)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x441a9bd5",
    "signature": "acquiredRecoveryShares(address)",
    "facet": "recoveryFundLens",
    "scope": "product"
  },
  {
    "selector": "0x452115d6",
    "signature": "cancel(address[],uint256[],bytes[],bytes32)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x4bf5d7e9",
    "signature": "CLOCK_MODE()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x4e62da25",
    "signature": "setVotingDelay(uint48,uint48)",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0x52ef6b2c",
    "signature": "facetAddresses()",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0x544ffc9c",
    "signature": "proposalVotes(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x54b02e3b",
    "signature": "onRecoveryShareRedemption(address,uint256,address,uint256,uint256)",
    "facet": "recoveryFund",
    "scope": "product"
  },
  {
    "selector": "0x54fd4d50",
    "signature": "version()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x56781388",
    "signature": "castVote(uint256,uint8)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x587cde1e",
    "signature": "delegates(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x5aa21375",
    "signature": "proposalExpiresAt(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x5c19a95c",
    "signature": "delegate(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x5c975abb",
    "signature": "paused()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x69c61caa",
    "signature": "setExecutionGracePeriod(uint48,uint48)",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0x6fcfff45",
    "signature": "numCheckpoints(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x70a08231",
    "signature": "balanceOf(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x75b24ebe",
    "signature": "canPause(address)",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x7a0ed627",
    "signature": "facets()",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0x7b1b6abf",
    "signature": "setExecutionDelay(uint48,uint48)",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0x7b3c71d3",
    "signature": "castVoteWithReason(uint256,uint8,string)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x7d5e81e2",
    "signature": "propose(address[],uint256[],bytes[],string)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x7ecebe00",
    "signature": "nonces(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x8456cb59",
    "signature": "pause()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x84b0196e",
    "signature": "eip712Domain()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x8886834b",
    "signature": "onCygldOutflow(address,address,uint256,uint256,uint256)",
    "facet": "recoveryFund",
    "scope": "product"
  },
  {
    "selector": "0x88cfce56",
    "signature": "safeWallet()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x8b257989",
    "signature": "executionDelay()",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0x8b313110",
    "signature": "trustedRecoveryFundCore()",
    "facet": "recoveryFundLens",
    "scope": "product"
  },
  {
    "selector": "0x8e539e8c",
    "signature": "getPastTotalSupply(uint256)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x8ff262e3",
    "signature": "castVoteBySig(uint256,uint8,address,bytes)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x9010d07c",
    "signature": "getRoleMember(bytes32,uint256)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x91d14854",
    "signature": "hasRole(bytes32,address)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x91ddadf4",
    "signature": "clock()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0x95d89b41",
    "signature": "symbol()",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x9ab24eb0",
    "signature": "getVotes(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x9cc2d2ce",
    "signature": "setQuorumNumerator(uint8,uint8)",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0xa217fddf",
    "signature": "DEFAULT_ADMIN_ROLE()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xa3246ad3",
    "signature": "getRoleMembers(bytes32)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xa7713a70",
    "signature": "quorumNumerator()",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0xa8f8a668",
    "signature": "getProposalId(address[],uint256[],bytes[],bytes32)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xa9059cbb",
    "signature": "transfer(address,uint256)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xa9a95294",
    "signature": "proposalNeedsQueuing(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xab58fb8e",
    "signature": "proposalEta(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xadfca15e",
    "signature": "facetFunctionSelectors(address)",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0xb58131b0",
    "signature": "proposalThreshold()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xb8b17531",
    "signature": "setSafeWallet(address,address)",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0xbbcde2c6",
    "signature": "previewAssetRecoveryFundPurchase(address,uint256)",
    "facet": "recoveryFundLens",
    "scope": "product"
  },
  {
    "selector": "0xbc197c81",
    "signature": "onERC1155BatchReceived(address,address,uint256[],uint256[],bytes)",
    "facet": "recoveryFund",
    "scope": "product"
  },
  {
    "selector": "0xbd1ff441",
    "signature": "treasuryWithdraw(address,address,uint256)",
    "facet": "treasury",
    "scope": "product"
  },
  {
    "selector": "0xc01f9e37",
    "signature": "proposalDeadline(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xc3cda520",
    "signature": "delegateBySig(address,uint256,uint256,uint8,bytes32,bytes32)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xc59057e4",
    "signature": "hashProposal(address[],uint256[],bytes[],bytes32)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xc723c768",
    "signature": "onRecoveryShareOutflow(address,address,uint256[],uint256[])",
    "facet": "recoveryFund",
    "scope": "product"
  },
  {
    "selector": "0xc8a81e3b",
    "signature": "onCygldApprovalChange(address,uint256,uint256,uint256,uint256)",
    "facet": "recoveryFund",
    "scope": "product"
  },
  {
    "selector": "0xca15c873",
    "signature": "getRoleMemberCount(bytes32)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xcdffacc6",
    "signature": "facetAddress(bytes4)",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0xd08cc542",
    "signature": "assetRecoveryFund(address)",
    "facet": "recoveryFundLens",
    "scope": "product"
  },
  {
    "selector": "0xd090d134",
    "signature": "canUnpause(address)",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0xd505accf",
    "signature": "permit(address,address,uint256,uint256,uint8,bytes32,bytes32)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xd547741f",
    "signature": "revokeRole(bytes32,address)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xdd4e2ba5",
    "signature": "COUNTING_MODE()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xdd62ed3e",
    "signature": "allowance(address,address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xdeaaa7cc",
    "signature": "BALLOT_TYPEHASH()",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xeb9019d4",
    "signature": "getVotes(address,uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xec0a12d9",
    "signature": "executionGracePeriod()",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0xf1127ed8",
    "signature": "checkpoints(address,uint32)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xf23a6e61",
    "signature": "onERC1155Received(address,address,uint256,uint256,bytes)",
    "facet": "recoveryFund",
    "scope": "product"
  },
  {
    "selector": "0xf4c3ff58",
    "signature": "setProposalThresholdNumerator(uint32,uint32)",
    "facet": "governorSettings",
    "scope": "product"
  },
  {
    "selector": "0xfb999fcb",
    "signature": "proposalQuorum(uint256)",
    "facet": "governorCore",
    "scope": "product"
  },
  {
    "selector": "0xfc0c546a",
    "signature": "token()",
    "facet": "governorCore",
    "scope": "product"
  }
] as const;

export const GOVERNANCE_DIAMOND_INTERFACE_ID = "0x3290c796" as const;

export const GOVERNANCE_DIAMOND_ERC165_ADVERTISED = false as const;
