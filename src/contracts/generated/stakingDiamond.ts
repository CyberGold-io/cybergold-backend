// Generated from the compiled release facets. Do not edit by hand.
export const STAKING_DIAMOND_ABI = [
  {
    "type": "error",
    "name": "AccessControlBadConfirmation",
    "inputs": []
  },
  {
    "type": "error",
    "name": "AccessControlEnforcedDefaultAdminDelay",
    "inputs": [
      {
        "name": "schedule",
        "type": "uint48",
        "internalType": "uint48"
      }
    ]
  },
  {
    "type": "error",
    "name": "AccessControlEnforcedDefaultAdminRules",
    "inputs": []
  },
  {
    "type": "error",
    "name": "AccessControlInvalidDefaultAdmin",
    "inputs": [
      {
        "name": "defaultAdmin",
        "type": "address",
        "internalType": "address"
      }
    ]
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
    "name": "AdapterNotSet",
    "inputs": []
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
    "name": "ClaimableInsufficient",
    "inputs": [
      {
        "name": "claimable",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "requested",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "CriticalRoleInitializationInvariant",
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
    "name": "CriticalRoleMembersAlreadyPresent",
    "inputs": [
      {
        "name": "role",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "memberCount",
        "type": "uint256",
        "internalType": "uint256"
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
    "name": "DefaultAdminDelayImmutable",
    "inputs": []
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
    "name": "DuplicateWithdrawer",
    "inputs": [
      {
        "name": "withdrawer",
        "type": "address",
        "internalType": "address"
      }
    ]
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
    "name": "ERC4626ExceededMaxDeposit",
    "inputs": [
      {
        "name": "receiver",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "assets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "max",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC4626ExceededMaxMint",
    "inputs": [
      {
        "name": "receiver",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "max",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC4626ExceededMaxRedeem",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "max",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC4626ExceededMaxWithdraw",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "assets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "max",
        "type": "uint256",
        "internalType": "uint256"
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
    "name": "FeeTooHigh",
    "inputs": []
  },
  {
    "type": "error",
    "name": "FundManagerQueryFailed",
    "inputs": []
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
    "name": "InvalidAllocator",
    "inputs": [
      {
        "name": "allocator",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "InvalidDefaultAdminCandidate",
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
    "name": "InvalidInitialization",
    "inputs": []
  },
  {
    "type": "error",
    "name": "InvalidNonce",
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
    "name": "InvalidSigner",
    "inputs": []
  },
  {
    "type": "error",
    "name": "InvalidSleeveArrays",
    "inputs": []
  },
  {
    "type": "error",
    "name": "MinCygldOutNotMet",
    "inputs": [
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "minRequired",
        "type": "uint256",
        "internalType": "uint256"
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
    "name": "NotControllerOrOperator",
    "inputs": []
  },
  {
    "type": "error",
    "name": "NotInitializing",
    "inputs": []
  },
  {
    "type": "error",
    "name": "NotQueue",
    "inputs": []
  },
  {
    "type": "error",
    "name": "PerformanceFeeChangeNoop",
    "inputs": []
  },
  {
    "type": "error",
    "name": "PerformanceFeeCurrentMismatch",
    "inputs": [
      {
        "name": "expectedPerformanceFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualPerformanceFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "QueueNotConfigured",
    "inputs": []
  },
  {
    "type": "error",
    "name": "ReadySharesInvariant",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
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
    "name": "RedeemViaQueue",
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
    "name": "RequestNotCancellable",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RequestNotReady",
    "inputs": []
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
    "name": "SignatureExpired",
    "inputs": []
  },
  {
    "type": "error",
    "name": "SleeveAssetMismatch",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expectedAsset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "SleeveExceeded",
    "inputs": []
  },
  {
    "type": "error",
    "name": "SleeveNotApproved",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "SleeveNotRegistered",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "SleevePrincipalNotCleared",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "principal",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "SleeveStakingDiamondMismatch",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expectedStakingDiamond",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "UnsolicitedEscrowDisabled",
    "inputs": []
  },
  {
    "type": "error",
    "name": "ZeroAddress",
    "inputs": []
  },
  {
    "type": "error",
    "name": "ZeroAmount",
    "inputs": []
  },
  {
    "type": "error",
    "name": "ZeroAsset",
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
    "name": "AutoProcessMaxSet",
    "inputs": [
      {
        "name": "previousLimit",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newLimit",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ClaimExpirySet",
    "inputs": [
      {
        "name": "previousExpiry",
        "type": "uint64",
        "indexed": false,
        "internalType": "uint64"
      },
      {
        "name": "newExpiry",
        "type": "uint64",
        "indexed": false,
        "internalType": "uint64"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ClaimableTotalAnomaly",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "source",
        "type": "uint8",
        "indexed": false,
        "internalType": "uint8"
      },
      {
        "name": "delta",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "before",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ControllerOperatorSet",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "operator",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "approved",
        "type": "bool",
        "indexed": false,
        "internalType": "bool"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "DefaultAdminDelayChangeCanceled",
    "inputs": [],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "DefaultAdminDelayChangeScheduled",
    "inputs": [
      {
        "name": "newDelay",
        "type": "uint48",
        "indexed": false,
        "internalType": "uint48"
      },
      {
        "name": "effectSchedule",
        "type": "uint48",
        "indexed": false,
        "internalType": "uint48"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "DefaultAdminTransferCanceled",
    "inputs": [],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "DefaultAdminTransferScheduled",
    "inputs": [
      {
        "name": "newAdmin",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "acceptSchedule",
        "type": "uint48",
        "indexed": false,
        "internalType": "uint48"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "Deposit",
    "inputs": [
      {
        "name": "sender",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "assets",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "shares",
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
    "name": "DonatedProfitAsCygld",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "asset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "profitAssetsIn",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "cygldOutTotal",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "feeCygld",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "donatedCygld",
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
    "name": "FundManagerHealthChanged",
    "inputs": [
      {
        "name": "healthy",
        "type": "bool",
        "indexed": false,
        "internalType": "bool"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "HeadSweepLimitSet",
    "inputs": [
      {
        "name": "previousLimit",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newLimit",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
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
    "name": "OwnerOperatorSet",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "operator",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "approved",
        "type": "bool",
        "indexed": false,
        "internalType": "bool"
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
    "name": "PerformanceFeeSet",
    "inputs": [
      {
        "name": "feePpm",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ReadyBoundaryAdvanced",
    "inputs": [
      {
        "name": "newBoundaryId",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "requestsAdvanced",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RedeemRequest",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "requestId",
        "type": "uint256",
        "indexed": true,
        "internalType": "uint256"
      },
      {
        "name": "sender",
        "type": "address",
        "indexed": false,
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RequestCancelled",
    "inputs": [
      {
        "name": "requestId",
        "type": "uint256",
        "indexed": true,
        "internalType": "uint256"
      },
      {
        "name": "controller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RequestClaimed",
    "inputs": [
      {
        "name": "id",
        "type": "uint256",
        "indexed": true,
        "internalType": "uint256"
      },
      {
        "name": "controller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "owner",
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
        "name": "assetsOut",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RequestExpired",
    "inputs": [
      {
        "name": "requestId",
        "type": "uint256",
        "indexed": true,
        "internalType": "uint256"
      },
      {
        "name": "controller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RequestPartiallyClaimed",
    "inputs": [
      {
        "name": "id",
        "type": "uint256",
        "indexed": true,
        "internalType": "uint256"
      },
      {
        "name": "controller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "sharesConsumed",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "assetsOut",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RequestPromoted",
    "inputs": [
      {
        "name": "id",
        "type": "uint256",
        "indexed": true,
        "internalType": "uint256"
      },
      {
        "name": "controller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "shares",
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
    "name": "SleeveAllocated",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "asset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "requested",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "used",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "SleeveApprovalUpdated",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "approved",
        "type": "bool",
        "indexed": false,
        "internalType": "bool"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "SleeveDeallocated",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "asset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "requested",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "returned",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "SleeveRegistered",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "asset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "SwapAdapterSet",
    "inputs": [
      {
        "name": "adapter",
        "type": "address",
        "indexed": false,
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
    "name": "TreasurySet",
    "inputs": [
      {
        "name": "treasury",
        "type": "address",
        "indexed": false,
        "internalType": "address"
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
    "name": "Withdraw",
    "inputs": [
      {
        "name": "sender",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "receiver",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "assets",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "shares",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "function",
    "name": "ALLOCATOR_ROLE",
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
    "name": "MAX_PERFORMANCE_FEE_PPM",
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
    "name": "REQUEST_REDEEM_TYPEHASH",
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
    "name": "WITHDRAWER_ROLE",
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
    "name": "acceptDefaultAdminTransfer",
    "inputs": [],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "allocate",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "assets",
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
        "name": "used",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
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
    "name": "asset",
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
    "name": "autoProcessMax",
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
    "name": "beginDefaultAdminTransfer",
    "inputs": [
      {
        "name": "newAdmin",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
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
    "name": "cancelDefaultAdminTransfer",
    "inputs": [],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "cancelRequest",
    "inputs": [
      {
        "name": "requestId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "sharesReturned",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "changeDefaultAdminDelay",
    "inputs": [
      {
        "name": "",
        "type": "uint48",
        "internalType": "uint48"
      }
    ],
    "outputs": [],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "claimExpiry",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint64",
        "internalType": "uint64"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "claimRequest",
    "inputs": [
      {
        "name": "requestId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "receiver",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "assetsOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "claimRequestUpTo",
    "inputs": [
      {
        "name": "requestId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "maxAssets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "receiver",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "assetsOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "claimableRedeemRequest",
    "inputs": [
      {
        "name": "requestId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "controller",
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
    "name": "claimableShares",
    "inputs": [
      {
        "name": "controller",
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
    "name": "claimableSharesTotal",
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
    "name": "controllerOpenQueries",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "ids",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "controllerOpenQueries",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "start",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "limit",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "ids",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "total",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "nextStart",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "convertToAssets",
    "inputs": [
      {
        "name": "shares",
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
    "name": "convertToShares",
    "inputs": [
      {
        "name": "assets",
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
    "name": "createdAt",
    "inputs": [
      {
        "name": "id",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint64",
        "internalType": "uint64"
      }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "custodyBalance",
    "inputs": [
      {
        "name": "token",
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
    "name": "cygld",
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
    "name": "deallocate",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "assets",
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
        "name": "returned",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
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
    "name": "defaultAdmin",
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
    "name": "defaultAdminDelay",
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
    "name": "defaultAdminDelayIncreaseWait",
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
    "name": "deposit",
    "inputs": [
      {
        "name": "assets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "receiver",
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
    "stateMutability": "nonpayable"
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
    "name": "escrowFrom",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
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
    "name": "harvestAndDonateAsCygld",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "minCygldOut",
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
        "name": "profitAssets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "cygldOut",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "feeCygld",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "donatedCygld",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
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
    "name": "headId",
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
    "name": "headSweepLimit",
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
    "name": "investableFor",
    "inputs": [
      {
        "name": "asset",
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
    "name": "isExpired",
    "inputs": [
      {
        "name": "id",
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
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "isReady",
    "inputs": [
      {
        "name": "id",
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
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "liquidityBreakdown",
    "inputs": [],
    "outputs": [
      {
        "name": "breakdown",
        "type": "tuple",
        "internalType": "struct VaultFacet.LiquidityBreakdown",
        "components": [
          {
            "name": "idleAssets",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "claimableAssets",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "strategyAssets",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "custodyAssets",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "totalManagedAssets",
            "type": "uint256",
            "internalType": "uint256"
          }
        ]
      },
      {
        "name": "healthy",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "maxDeposit",
    "inputs": [
      {
        "name": "receiver",
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
    "name": "maxMint",
    "inputs": [
      {
        "name": "receiver",
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
    "name": "maxRedeem",
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
    "name": "maxWithdraw",
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
    "name": "mint",
    "inputs": [
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "receiver",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "assets",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
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
    "name": "payout",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "receiver",
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
        "name": "assetsOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "pendingDefaultAdmin",
    "inputs": [],
    "outputs": [
      {
        "name": "newAdmin",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "schedule",
        "type": "uint48",
        "internalType": "uint48"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "pendingDefaultAdminDelay",
    "inputs": [],
    "outputs": [
      {
        "name": "newDelay",
        "type": "uint48",
        "internalType": "uint48"
      },
      {
        "name": "schedule",
        "type": "uint48",
        "internalType": "uint48"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "performanceFeePpm",
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
    "name": "position",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "principalAssets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "totalAssets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "pnl",
        "type": "int256",
        "internalType": "int256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "previewDeposit",
    "inputs": [
      {
        "name": "assets",
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
    "name": "previewMint",
    "inputs": [
      {
        "name": "shares",
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
    "name": "previewRedeem",
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
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "previewWithdraw",
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
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "pure"
  },
  {
    "type": "function",
    "name": "principalPerAsset",
    "inputs": [
      {
        "name": "asset",
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
    "name": "processQueue",
    "inputs": [
      {
        "name": "maxRequests",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "processed",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "purgeExpired",
    "inputs": [
      {
        "name": "requestIds",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "outputs": [
      {
        "name": "expiredCount",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "queueAggregates",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "agg",
        "type": "tuple",
        "internalType": "struct LensFacet.QueueAggregates",
        "components": [
          {
            "name": "headId",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "tailId",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "readyBoundaryId",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "claimExpiry",
            "type": "uint64",
            "internalType": "uint64"
          },
          {
            "name": "headSweepLimit",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "autoProcessMax",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "seqInBlock",
            "type": "uint64",
            "internalType": "uint64"
          },
          {
            "name": "claimableController",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "claimableTotal",
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
    "name": "queueRequests",
    "inputs": [
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "out",
        "type": "tuple[]",
        "internalType": "struct LensFacet.QueueRequestView[]",
        "components": [
          {
            "name": "id",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "controller",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "owner",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "shares",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "ready",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "expired",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "readyAt",
            "type": "uint64",
            "internalType": "uint64"
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "readyAtFor",
    "inputs": [
      {
        "name": "id",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint64",
        "internalType": "uint64"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "readyBoundaryId",
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
    "name": "redeem",
    "inputs": [
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "receiver",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "assetsOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "registerSleeve",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
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
    "name": "requestRedeem",
    "inputs": [
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "requestId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "requestRedeemBySig",
    "inputs": [
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
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
    "outputs": [
      {
        "name": "requestId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "returnShares",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
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
    "name": "rollbackDefaultAdminDelay",
    "inputs": [],
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
    "name": "seqInBlock",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint64",
        "internalType": "uint64"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "setAutoProcessMax",
    "inputs": [
      {
        "name": "newLimit",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setClaimExpiry",
    "inputs": [
      {
        "name": "expirySeconds",
        "type": "uint64",
        "internalType": "uint64"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setControllerOperator",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "approved",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setHeadSweepLimit",
    "inputs": [
      {
        "name": "newLimit",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setOwnerOperator",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "approved",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setPerformanceFee",
    "inputs": [
      {
        "name": "currentPerformanceFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "newFeePpm",
        "type": "uint256",
        "internalType": "uint256"
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
    "name": "setSleeveApproval",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "approved",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setSwapAdapter",
    "inputs": [
      {
        "name": "adapter",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setTreasury",
    "inputs": [
      {
        "name": "treasury_",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "share",
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
    "name": "sleeveConfig",
    "inputs": [
      {
        "name": "sleeve",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "cfg",
        "type": "tuple",
        "internalType": "struct LibAppStorage.SleeveConfig",
        "components": [
          {
            "name": "registered",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "approved",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "asset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "principalAssets",
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
    "name": "sleevePositions",
    "inputs": [],
    "outputs": [
      {
        "name": "positions",
        "type": "tuple[]",
        "internalType": "struct LensFacet.SleevePosition[]",
        "components": [
          {
            "name": "sleeve",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "asset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "principalAssets",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "totalAssets",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "pnl",
            "type": "int256",
            "internalType": "int256"
          },
          {
            "name": "approved",
            "type": "bool",
            "internalType": "bool"
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "sleeves",
    "inputs": [],
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
    "name": "stakerAssetsInSleeves",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "total",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "stakerRatioFp18",
    "inputs": [],
    "outputs": [
      {
        "name": "ratioFp18",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "stakingLaunchState",
    "inputs": [],
    "outputs": [
      {
        "name": "phase",
        "type": "uint8",
        "internalType": "enum LibStakingLaunch.Phase"
      },
      {
        "name": "finalizationHash",
        "type": "bytes32",
        "internalType": "bytes32"
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
    "name": "swapAdapter",
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
    "name": "sweepExpiredHead",
    "inputs": [
      {
        "name": "max",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "purged",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
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
    "name": "systemState",
    "inputs": [],
    "outputs": [
      {
        "name": "s",
        "type": "tuple",
        "internalType": "struct LensFacet.SystemState",
        "components": [
          {
            "name": "asset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "paused",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "fundManagerHealthy",
            "type": "bool",
            "internalType": "bool"
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "tailId",
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
    "name": "totalAssets",
    "inputs": [],
    "outputs": [
      {
        "name": "assets",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "totalAssetsSafe",
    "inputs": [],
    "outputs": [
      {
        "name": "assets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "healthy",
        "type": "bool",
        "internalType": "bool"
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
    "name": "transferTo",
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
    "name": "treasury",
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
    "name": "viewRequest",
    "inputs": [
      {
        "name": "id",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "controller",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "createdAtTs",
        "type": "uint64",
        "internalType": "uint64"
      },
      {
        "name": "readyAtTs",
        "type": "uint64",
        "internalType": "uint64"
      },
      {
        "name": "ready",
        "type": "bool",
        "internalType": "bool"
      },
      {
        "name": "expired",
        "type": "bool",
        "internalType": "bool"
      },
      {
        "name": "assetsAtCurrentPrice",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "paused_",
        "type": "bool",
        "internalType": "bool"
      },
      {
        "name": "healthy",
        "type": "bool",
        "internalType": "bool"
      },
      {
        "name": "claimable",
        "type": "bool",
        "internalType": "bool"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "withdraw",
    "inputs": [
      {
        "name": "assets",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "receiver",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "sharesBurned",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  }
] as const;

export const STAKING_DIAMOND_FUNCTIONS = [
  {
    "selector": "0x01e1d114",
    "signature": "totalAssets()",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x01ffc9a7",
    "signature": "supportsInterface(bytes4)",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0x022d63fb",
    "signature": "defaultAdminDelayIncreaseWait()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x02545bcb",
    "signature": "setControllerOperator(address,bool)",
    "facet": "queueOperator",
    "scope": "product"
  },
  {
    "selector": "0x035c0801",
    "signature": "readyAtFor(uint256)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x06fdde03",
    "signature": "name()",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x07389841",
    "signature": "upgraderRole()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x07a2d13a",
    "signature": "convertToAssets(uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x095ea7b3",
    "signature": "approve(address,uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x0a28a477",
    "signature": "previewWithdraw(uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x0aa6220b",
    "signature": "rollbackDefaultAdminDelay()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x0d11c635",
    "signature": "facetGeneration(bytes32)",
    "facet": "cut",
    "scope": "base"
  },
  {
    "selector": "0x15d6f1a8",
    "signature": "headId()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x16e30dcf",
    "signature": "setOwnerOperator(address,bool)",
    "facet": "queueOperator",
    "scope": "product"
  },
  {
    "selector": "0x18160ddd",
    "signature": "totalSupply()",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x1c75e369",
    "signature": "allocate(address,uint256,bytes)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x1f931c1c",
    "signature": "diamondCut((address,uint8,bytes4[])[],address,bytes)",
    "facet": "cut",
    "scope": "base"
  },
  {
    "selector": "0x20dd22be",
    "signature": "tailId()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x23b872dd",
    "signature": "transferFrom(address,address,uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x248a9ca3",
    "signature": "getRoleAdmin(bytes32)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x26e85250",
    "signature": "viewRequest(uint256)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x29e999f4",
    "signature": "claimRequest(uint256,address)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0x2d293586",
    "signature": "sleevePositions()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x2d379033",
    "signature": "investableFor(address)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x2dbcdd2d",
    "signature": "controllerOpenQueries(address)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x2f2ff15d",
    "signature": "grantRole(bytes32,address)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x3015394c",
    "signature": "cancelRequest(uint256)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0x313ce567",
    "signature": "decimals()",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x31b5f955",
    "signature": "performanceFeePpm()",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x34129a59",
    "signature": "registerSleeve(address,address)",
    "facet": "registry",
    "scope": "product"
  },
  {
    "selector": "0x3644e515",
    "signature": "DOMAIN_SEPARATOR()",
    "facet": "queueSig",
    "scope": "product"
  },
  {
    "selector": "0x36568abe",
    "signature": "renounceRole(bytes32,address)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x38d52e0f",
    "signature": "asset()",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x3b3c186d",
    "signature": "controllerOpenQueries(address,uint256,uint256)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x3f4ba83a",
    "signature": "unpause()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x402d267d",
    "signature": "maxDeposit(address)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x42ddb9f0",
    "signature": "setClaimExpiry(uint64)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0x42e2ee9e",
    "signature": "stakerAssetsInSleeves(address)",
    "facet": "registry",
    "scope": "product"
  },
  {
    "selector": "0x440e52bf",
    "signature": "sweepExpiredHead(uint256)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0x4cdad506",
    "signature": "previewRedeem(uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x4f5ad9c5",
    "signature": "claimableShares(address)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x50a1676e",
    "signature": "createdAt(uint256)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x50df8f71",
    "signature": "isReady(uint256)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x52ef6b2c",
    "signature": "facetAddresses()",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0x549230c9",
    "signature": "deallocate(address,uint256,bytes)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x569c7fd1",
    "signature": "autoProcessMax()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x5c975abb",
    "signature": "paused()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x5e39974f",
    "signature": "REQUEST_REDEEM_TYPEHASH()",
    "facet": "queueSig",
    "scope": "product"
  },
  {
    "selector": "0x5ff4d706",
    "signature": "stakingLaunchState()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x6114d32c",
    "signature": "claimableSharesTotal()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x61d027b3",
    "signature": "treasury()",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x634e93da",
    "signature": "beginDefaultAdminTransfer(address)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x649a5ec7",
    "signature": "changeDefaultAdminDelay(uint48)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x676f3cb7",
    "signature": "readyBoundaryId()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x69336753",
    "signature": "principalPerAsset(address)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x69e08a0c",
    "signature": "custodyBalance(address)",
    "facet": "custody",
    "scope": "product"
  },
  {
    "selector": "0x6e553f65",
    "signature": "deposit(uint256,address)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x70a08231",
    "signature": "balanceOf(address)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x70c75d14",
    "signature": "headSweepLimit()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x75b24ebe",
    "signature": "canPause(address)",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x77bb1eb9",
    "signature": "swapAdapter()",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x7a0ed627",
    "signature": "facets()",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0x7d41c86e",
    "signature": "requestRedeem(uint256,address,address)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0x7d85ad6a",
    "signature": "MAX_PERFORMANCE_FEE_PPM()",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x7ecebe00",
    "signature": "nonces(address)",
    "facet": "queueSig",
    "scope": "product"
  },
  {
    "selector": "0x8456cb59",
    "signature": "pause()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x84ef8ffc",
    "signature": "defaultAdmin()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x8544a0ae",
    "signature": "queueRequests(address)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x85f438c1",
    "signature": "WITHDRAWER_ROLE()",
    "facet": "custody",
    "scope": "product"
  },
  {
    "selector": "0x8654db41",
    "signature": "setSleeveApproval(address,bool)",
    "facet": "registry",
    "scope": "product"
  },
  {
    "selector": "0x86af88f3",
    "signature": "stakerRatioFp18()",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0x88cfce56",
    "signature": "safeWallet()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x8b198025",
    "signature": "returnShares(address,uint256)",
    "facet": "vault",
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
    "selector": "0x94bf804d",
    "signature": "mint(uint256,address)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x95d89b41",
    "signature": "symbol()",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0x991292e3",
    "signature": "systemState()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xa1eda53c",
    "signature": "pendingDefaultAdminDelay()",
    "facet": "access",
    "scope": "base"
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
    "selector": "0xa5f2a152",
    "signature": "transferTo(address,address,uint256)",
    "facet": "custody",
    "scope": "product"
  },
  {
    "selector": "0xa8d5fd65",
    "signature": "share()",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xa9059cbb",
    "signature": "transfer(address,uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xadfca15e",
    "signature": "facetFunctionSelectors(address)",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0xb3d7f6b9",
    "signature": "previewMint(uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xb4260cbc",
    "signature": "setPerformanceFee(uint256,uint256)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0xb460af94",
    "signature": "withdraw(uint256,address,address)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0xb7648fb9",
    "signature": "position(address)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0xb826ee54",
    "signature": "setSwapAdapter(address)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0xb8b17531",
    "signature": "setSafeWallet(address,address)",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0xba087652",
    "signature": "redeem(uint256,address,address)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0xc06dada3",
    "signature": "requestRedeemBySig(uint256,address,address,uint256,uint8,bytes32,bytes32)",
    "facet": "queueSig",
    "scope": "product"
  },
  {
    "selector": "0xc16b5039",
    "signature": "claimRequestUpTo(uint256,uint256,address)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0xc4188020",
    "signature": "sleeves()",
    "facet": "registry",
    "scope": "product"
  },
  {
    "selector": "0xc526c90a",
    "signature": "harvestAndDonateAsCygld(address,uint256,bytes)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0xc63d75b6",
    "signature": "maxMint(address)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xc6e6f592",
    "signature": "convertToShares(uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xc81cbaa1",
    "signature": "ALLOCATOR_ROLE()",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0xca15c873",
    "signature": "getRoleMemberCount(bytes32)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xcc8463c8",
    "signature": "defaultAdminDelay()",
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
    "selector": "0xce94eb96",
    "signature": "payout(address,address,address,uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xce96cb77",
    "signature": "maxWithdraw(address)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xcefc1429",
    "signature": "acceptDefaultAdminTransfer()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xcf6eefb7",
    "signature": "pendingDefaultAdmin()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xd03384b8",
    "signature": "claimExpiry()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xd090d134",
    "signature": "canUnpause(address)",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0xd38eb9d3",
    "signature": "escrowFrom(address,uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xd3e99e1c",
    "signature": "cygld()",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0xd547741f",
    "signature": "revokeRole(bytes32,address)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xd602b9fd",
    "signature": "cancelDefaultAdminTransfer()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xd905777e",
    "signature": "maxRedeem(address)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xd9548e53",
    "signature": "isExpired(uint256)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xd9b7c250",
    "signature": "purgeExpired(uint256[])",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0xdc6b247f",
    "signature": "queueAggregates(address)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xdc900765",
    "signature": "processQueue(uint256)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0xdd62ed3e",
    "signature": "allowance(address,address)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xdf6e6142",
    "signature": "totalAssetsSafe()",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xe18854ed",
    "signature": "setHeadSweepLimit(uint256)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0xe43a3230",
    "signature": "setAutoProcessMax(uint256)",
    "facet": "queue",
    "scope": "product"
  },
  {
    "selector": "0xe5a44482",
    "signature": "liquidityBreakdown()",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xeaed1d07",
    "signature": "claimableRedeemRequest(uint256,address)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xef8b30f7",
    "signature": "previewDeposit(uint256)",
    "facet": "vault",
    "scope": "product"
  },
  {
    "selector": "0xf0f44260",
    "signature": "setTreasury(address)",
    "facet": "fund",
    "scope": "product"
  },
  {
    "selector": "0xf3f78be5",
    "signature": "seqInBlock()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xf4d5808c",
    "signature": "sleeveConfig(address)",
    "facet": "registry",
    "scope": "product"
  }
] as const;

export const STAKING_DIAMOND_INTERFACE_ID = "0x4c02b118" as const;

export const STAKING_DIAMOND_ERC165_ADVERTISED = true as const;
