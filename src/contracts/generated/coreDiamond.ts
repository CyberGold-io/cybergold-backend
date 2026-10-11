// Generated from the compiled release facets. Do not edit by hand.
export const CORE_DIAMOND_ABI = [
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
    "name": "AccountCallbackFailed",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "callback",
        "type": "bytes4",
        "internalType": "bytes4"
      }
    ]
  },
  {
    "type": "error",
    "name": "AccountCallbackMagicMismatch",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "callback",
        "type": "bytes4",
        "internalType": "bytes4"
      },
      {
        "name": "returnedWord",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "AccountCallbackReturnMalformed",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "callback",
        "type": "bytes4",
        "internalType": "bytes4"
      },
      {
        "name": "returnDataLength",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketAssetDecimalsMissing",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketAssetDecimalsTooLarge",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "decimals",
        "type": "uint8",
        "internalType": "uint8"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketAssetMismatch",
    "inputs": [
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "provided",
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
    "name": "BasketAssetNotFound",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketChangeNoop",
    "inputs": []
  },
  {
    "type": "error",
    "name": "BasketCurrentMismatch",
    "inputs": [
      {
        "name": "expectedBasketHash",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "actualBasketHash",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketDuplicateAsset",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketEmpty",
    "inputs": []
  },
  {
    "type": "error",
    "name": "BasketGoldRefLengthMismatch",
    "inputs": [
      {
        "name": "assetsLength",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "goldRefsLength",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketInsufficientPositiveTargets",
    "inputs": [
      {
        "name": "actual",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "required",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketLengthMismatch",
    "inputs": [
      {
        "name": "assetsLength",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "weightsLength",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketNotConfigured",
    "inputs": []
  },
  {
    "type": "error",
    "name": "BasketWeightsMismatch",
    "inputs": [
      {
        "name": "actualSum",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "expectedSum",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketZeroAsset",
    "inputs": [
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketZeroConversion",
    "inputs": [
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "BasketZeroCygldRef",
    "inputs": []
  },
  {
    "type": "error",
    "name": "BasketZeroGoldRef",
    "inputs": [
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
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
    "name": "CombinedAssetLimitExceeded",
    "inputs": [
      {
        "name": "basketCount",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "economicRecoveryCount",
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
    "name": "ControllerOnly",
    "inputs": []
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
    "name": "CygldSupplyCapExceeded",
    "inputs": [
      {
        "name": "currentSupply",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "requestedIncrease",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "cygldSupplyCap",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "CygldSupplyCapInvalid",
    "inputs": [
      {
        "name": "cap",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "currentSupply",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "globalMaxSupply",
        "type": "uint256",
        "internalType": "uint256"
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
    "name": "DiamondCutFacetRuntimeNotInitialized",
    "inputs": [
      {
        "name": "namespace",
        "type": "bytes32",
        "internalType": "bytes32"
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
        "name": "runtimeCodeHash",
        "type": "bytes32",
        "internalType": "bytes32"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutFacetVersionNotIncreasing",
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
      },
      {
        "name": "proposed",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "DiamondCutFacetVersionNotInitialized",
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
    "name": "DiamondCutInvalidFacetMetadata",
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
      },
      {
        "name": "version",
        "type": "uint64",
        "internalType": "uint64"
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
    "name": "ERC1155InsufficientBalance",
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
      },
      {
        "name": "tokenId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC1155InvalidApprover",
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
    "name": "ERC1155InvalidArrayLength",
    "inputs": [
      {
        "name": "idsLength",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "valuesLength",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC1155InvalidOperator",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "ERC1155InvalidReceiver",
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
    "name": "ERC1155InvalidSender",
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
    "name": "ERC1155MissingApprovalForAll",
    "inputs": [
      {
        "name": "operator",
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
    "name": "ExactNetGrossOverflow",
    "inputs": [
      {
        "name": "netCygldAmount",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "feePpm",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ExpectedOrderedBasketAssetsLengthMismatch",
    "inputs": [
      {
        "name": "providedLength",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualLength",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ExpectedPause",
    "inputs": []
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
    "name": "FacetInitVersionAlreadyInitialized",
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
      },
      {
        "name": "attempted",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "FacetLaunchMetadataInvalid",
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
      },
      {
        "name": "version",
        "type": "uint64",
        "internalType": "uint64"
      }
    ]
  },
  {
    "type": "error",
    "name": "FacetRuntimeAuthorizationConflict",
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
    "name": "FacetRuntimeUpgradeNotAuthorized",
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
      },
      {
        "name": "version",
        "type": "uint64",
        "internalType": "uint64"
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
    "name": "FacetVersionProbeFailed",
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
    "name": "FeeChangeNoop",
    "inputs": []
  },
  {
    "type": "error",
    "name": "FeeTooHigh",
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
    "name": "InsufficientSupply",
    "inputs": []
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
    "name": "IssuanceFeeCurrentMismatch",
    "inputs": [
      {
        "name": "expectedIssuanceFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualIssuanceFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "IssueAmountInAboveMaximum",
    "inputs": [
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "maximum",
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
    "name": "MaxTotalSupplyBelowCurrentSupply",
    "inputs": [
      {
        "name": "currentSupply",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "newMaxTotalSupply",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "MaxTotalSupplyChangeNoop",
    "inputs": []
  },
  {
    "type": "error",
    "name": "MaxTotalSupplyCurrentMismatch",
    "inputs": [
      {
        "name": "currentMaxTotalSupply",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualCurrentMaxTotalSupply",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "MaxTotalSupplyExceeded",
    "inputs": [
      {
        "name": "currentSupply",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "requestedIncrease",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "maxTotalSupply",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "MaxTotalSupplyNotSet",
    "inputs": []
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
    "name": "PayerDebitMismatch",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "payer",
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
    "name": "RebalanceAmountTooSmallAfterConversion",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "amount",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RebalanceInputNotUnderweight",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "side",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "magnitude",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RebalanceInsufficientOutput",
    "inputs": [
      {
        "name": "minAmountOut",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "amountOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RebalanceOutputNotOverweight",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "side",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "magnitude",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RebalanceOvershootsTarget",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RebalanceSameAsset",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RebalanceWorsensAsset",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "beforeSide",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "beforeMagnitude",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "afterSide",
        "type": "uint8",
        "internalType": "uint8"
      },
      {
        "name": "afterMagnitude",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecipientCreditMismatch",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "recipient",
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
    "name": "RecoveryAssetInvalid",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryEntitlementMismatch",
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
    "name": "RecoveryMinimumNotMet",
    "inputs": [
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
    "name": "RecoveryPageLimitInvalid",
    "inputs": [
      {
        "name": "limit",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryPoolAccountingInvariant",
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
    "name": "RecoveryPoolCustodyDeficit",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "rawCustody",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "requiredRaw",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryPoolImpairmentInvalid",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expected",
        "type": "bool",
        "internalType": "bool"
      },
      {
        "name": "actual",
        "type": "bool",
        "internalType": "bool"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryPoolStateMismatch",
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
    "name": "RecoveryRecipientInvalid",
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
    "name": "RecoveryShareAmountZero",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryShareAssetsNotAscending",
    "inputs": [
      {
        "name": "previousAsset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "currentAsset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryShareControllerOnly",
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
    "name": "RecoveryShareIdInvalid",
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
    "name": "RecoveryShareLengthMismatch",
    "inputs": [
      {
        "name": "assetsLength",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "amountsLength",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryShareOutputZero",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "shares",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RecoveryShareSupplyInvariant",
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
    "name": "RecoveryShareUnknown",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "RedemptionFeeCurrentMismatch",
    "inputs": [
      {
        "name": "expectedRedemptionFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualRedemptionFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RedemptionNoOutput",
    "inputs": []
  },
  {
    "type": "error",
    "name": "RedemptionOutputBelowMinimum",
    "inputs": [
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
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
    "name": "RedemptionOutputDescriptorMismatch",
    "inputs": [
      {
        "name": "index",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "providedKind",
        "type": "uint8",
        "internalType": "enum ICoreRedemption.TokenKind"
      },
      {
        "name": "providedToken",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "providedId",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualKind",
        "type": "uint8",
        "internalType": "enum ICoreRedemption.TokenKind"
      },
      {
        "name": "actualToken",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "actualId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "RedemptionOutputsLengthMismatch",
    "inputs": [
      {
        "name": "providedLength",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualLength",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
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
    "name": "ReserveActivationBalanceMismatch",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expectedRaw",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualRaw",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ReserveActivationStateInvalid",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "ReserveBalanceProbeUnavailable",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "ReserveDebitMismatch",
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
    "name": "ReserveExitPositiveEntitlement",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "exitEntitlementRaw",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ReserveLifecycleInvalid",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "expected",
        "type": "uint8",
        "internalType": "enum IRecoveryTypes.ReserveLifecycle"
      },
      {
        "name": "actual",
        "type": "uint8",
        "internalType": "enum IRecoveryTypes.ReserveLifecycle"
      }
    ]
  },
  {
    "type": "error",
    "name": "ReserveLifecycleOutstandingObligation",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "exitEntitlementRaw",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "poolRaw",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ReserveLifecycleTargetMismatch",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "lifecycle",
        "type": "uint8",
        "internalType": "enum IRecoveryTypes.ReserveLifecycle"
      },
      {
        "name": "targetPpm",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ReserveLifecycleTransitionInvalid",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "from",
        "type": "uint8",
        "internalType": "enum IRecoveryTypes.ReserveLifecycle"
      },
      {
        "name": "to",
        "type": "uint8",
        "internalType": "enum IRecoveryTypes.ReserveLifecycle"
      }
    ]
  },
  {
    "type": "error",
    "name": "ReserveZeroAddress",
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
    "name": "SettlementBoundsLengthMismatch",
    "inputs": [
      {
        "name": "providedLength",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "actualLength",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "StringsInsufficientHexLength",
    "inputs": [
      {
        "name": "value",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "length",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "TreasuryChangeNoop",
    "inputs": []
  },
  {
    "type": "error",
    "name": "TreasuryCurrentMismatch",
    "inputs": [
      {
        "name": "expectedTreasury",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "actualTreasury",
        "type": "address",
        "internalType": "address"
      }
    ]
  },
  {
    "type": "error",
    "name": "TreasuryNotSet",
    "inputs": []
  },
  {
    "type": "error",
    "name": "UnderDelivery",
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
        "name": "received",
        "type": "uint256",
        "internalType": "uint256"
      }
    ]
  },
  {
    "type": "error",
    "name": "ValueMustBeGreaterThanZero",
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
    "name": "ApprovalForAll",
    "inputs": [
      {
        "name": "account",
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
    "name": "BasketConfigured",
    "inputs": [
      {
        "name": "assets",
        "type": "address[]",
        "indexed": false,
        "internalType": "address[]"
      },
      {
        "name": "targetsPpm",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      },
      {
        "name": "goldRefGramsFp18",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      },
      {
        "name": "cygldRefGramsFp18",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "cygldPerUnitFp18",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "BasketUpdated",
    "inputs": [
      {
        "name": "previousBasketHash",
        "type": "bytes32",
        "indexed": false,
        "internalType": "bytes32"
      },
      {
        "name": "newBasketHash",
        "type": "bytes32",
        "indexed": false,
        "internalType": "bytes32"
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
    "name": "IssuanceFeePpmUpdated",
    "inputs": [
      {
        "name": "previousIssuanceFeePpm",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newIssuanceFeePpm",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "Issued",
    "inputs": [
      {
        "name": "caller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "reserve",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "treasury",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "grossCygldOut",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "netCygldOut",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "protocolFeeCygld",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "amountsIn",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "MaxTotalSupplyUpdated",
    "inputs": [
      {
        "name": "previousMaxTotalSupply",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newMaxTotalSupply",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
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
    "name": "RebalanceSwapped",
    "inputs": [
      {
        "name": "caller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "assetIn",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "assetOut",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "reserve",
        "type": "address",
        "indexed": false,
        "internalType": "address"
      },
      {
        "name": "amountIn",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "amountOut",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RecoveryActivated",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "addedCoreAttachedShares",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RecoveryRehabilitated",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "totalPoolRaw",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "coreRaw",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "externalRaw",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RecoverySharesRedeemed",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "account",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "recipient",
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
        "name": "liabilityReleasedRaw",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "rawAmountOut",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "Redeemed",
    "inputs": [
      {
        "name": "caller",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "reserve",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "treasury",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "grossCygldIn",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "netCygldIn",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "protocolFeeCygld",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "kinds",
        "type": "uint8[]",
        "indexed": false,
        "internalType": "enum ICoreRedemption.TokenKind[]"
      },
      {
        "name": "tokens",
        "type": "address[]",
        "indexed": false,
        "internalType": "address[]"
      },
      {
        "name": "ids",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      },
      {
        "name": "amounts",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "RedemptionFeePpmUpdated",
    "inputs": [
      {
        "name": "previousRedemptionFeePpm",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      },
      {
        "name": "newRedemptionFeePpm",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "ReserveLifecycleChanged",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
      {
        "name": "previousLifecycle",
        "type": "uint8",
        "indexed": false,
        "internalType": "enum IRecoveryTypes.ReserveLifecycle"
      },
      {
        "name": "newLifecycle",
        "type": "uint8",
        "indexed": false,
        "internalType": "enum IRecoveryTypes.ReserveLifecycle"
      },
      {
        "name": "exitEntitlementRaw",
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
    "name": "TransferBatch",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
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
        "name": "ids",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      },
      {
        "name": "values",
        "type": "uint256[]",
        "indexed": false,
        "internalType": "uint256[]"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "TransferSingle",
    "inputs": [
      {
        "name": "operator",
        "type": "address",
        "indexed": true,
        "internalType": "address"
      },
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
        "name": "id",
        "type": "uint256",
        "indexed": false,
        "internalType": "uint256"
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
    "name": "TreasuryUpdated",
    "inputs": [
      {
        "name": "previousTreasury",
        "type": "address",
        "indexed": false,
        "internalType": "address"
      },
      {
        "name": "newTreasury",
        "type": "address",
        "indexed": false,
        "internalType": "address"
      }
    ],
    "anonymous": false
  },
  {
    "type": "event",
    "name": "URI",
    "inputs": [
      {
        "name": "value",
        "type": "string",
        "indexed": false,
        "internalType": "string"
      },
      {
        "name": "id",
        "type": "uint256",
        "indexed": true,
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
    "name": "MAX_FEE_PPM",
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
    "name": "REDEMPTION_FEE_EXEMPT_ROLE",
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
    "name": "activateAsset",
    "inputs": [
      {
        "name": "request",
        "type": "tuple",
        "internalType": "struct IRecoveryTypes.AssetActivationRequest",
        "components": [
          {
            "name": "asset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "expectedLifecycle",
            "type": "uint8",
            "internalType": "enum IRecoveryTypes.ReserveLifecycle"
          },
          {
            "name": "expectedBasketHash",
            "type": "bytes32",
            "internalType": "bytes32"
          },
          {
            "name": "expectedActiveAvailableRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "resultingBasketAssets",
            "type": "address[]",
            "internalType": "address[]"
          },
          {
            "name": "resultingTargetsPpm",
            "type": "uint256[]",
            "internalType": "uint256[]"
          },
          {
            "name": "resultingGoldRefGramsFp18",
            "type": "uint256[]",
            "internalType": "uint256[]"
          }
        ]
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "activateRecovery",
    "inputs": [
      {
        "name": "request",
        "type": "tuple",
        "internalType": "struct IRecoveryTypes.RecoveryActivation",
        "components": [
          {
            "name": "impairedAsset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "expectedLifecycle",
            "type": "uint8",
            "internalType": "enum IRecoveryTypes.ReserveLifecycle"
          },
          {
            "name": "expectedBasketHash",
            "type": "bytes32",
            "internalType": "bytes32"
          },
          {
            "name": "expectedEntitlementRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "replacementBasketAssets",
            "type": "address[]",
            "internalType": "address[]"
          },
          {
            "name": "replacementTargetsPpm",
            "type": "uint256[]",
            "internalType": "uint256[]"
          },
          {
            "name": "replacementGoldRefGramsFp18",
            "type": "uint256[]",
            "internalType": "uint256[]"
          },
          {
            "name": "cygldSupplyCap",
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
    "name": "allowanceExposure",
    "inputs": [
      {
        "name": "owner",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "exposure",
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
    "name": "balanceOf",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "id",
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
    "name": "balanceOfBatch",
    "inputs": [
      {
        "name": "accounts",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "ids",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "basketAssets",
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
    "name": "basketConfigHash",
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
    "name": "basketCygldPerUnitFp18",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "basketGoldRefGramsFp18",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "basketTargetsPpm",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "uint256[]",
        "internalType": "uint256[]"
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
    "name": "beginReserveExit",
    "inputs": [
      {
        "name": "request",
        "type": "tuple",
        "internalType": "struct IRecoveryTypes.ReserveExitRequest",
        "components": [
          {
            "name": "asset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "expectedBasketHash",
            "type": "bytes32",
            "internalType": "bytes32"
          },
          {
            "name": "expectedExitEntitlementRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "resultingBasketAssets",
            "type": "address[]",
            "internalType": "address[]"
          },
          {
            "name": "resultingTargetsPpm",
            "type": "uint256[]",
            "internalType": "uint256[]"
          },
          {
            "name": "resultingGoldRefGramsFp18",
            "type": "uint256[]",
            "internalType": "uint256[]"
          }
        ]
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "burn",
    "inputs": [
      {
        "name": "from",
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
    "name": "burnRecoveryShares",
    "inputs": [
      {
        "name": "from",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "asset",
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
    "name": "contractURI",
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
    "name": "coreAttachedRecoveryAssets",
    "inputs": [],
    "outputs": [
      {
        "name": "assets",
        "type": "address[]",
        "internalType": "address[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "cygldRefGramsFp18",
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
    "name": "effectiveCygldSupplyCap",
    "inputs": [],
    "outputs": [
      {
        "name": "cygldSupplyCap",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
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
    "name": "finalizeReserveInactivation",
    "inputs": [
      {
        "name": "request",
        "type": "tuple",
        "internalType": "struct IRecoveryTypes.ReserveInactivationRequest",
        "components": [
          {
            "name": "asset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "expectedBasketHash",
            "type": "bytes32",
            "internalType": "bytes32"
          },
          {
            "name": "resultingBasketAssets",
            "type": "address[]",
            "internalType": "address[]"
          },
          {
            "name": "resultingTargetsPpm",
            "type": "uint256[]",
            "internalType": "uint256[]"
          },
          {
            "name": "resultingGoldRefGramsFp18",
            "type": "uint256[]",
            "internalType": "uint256[]"
          }
        ]
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "finalizeZeroEntitlementRecovery",
    "inputs": [
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
    "name": "isApprovedForAll",
    "inputs": [
      {
        "name": "account",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "operator",
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
    "name": "issuanceFeePpm",
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
    "name": "issue",
    "inputs": [
      {
        "name": "netCygldOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "issuedNetCygldOut",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "protocolFeeCygld",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "amountsIn",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "issueRecoveryShares",
    "inputs": [
      {
        "name": "to",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "assets",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "amounts",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "maxTotalSupply",
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
    "name": "mint",
    "inputs": [
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
    "name": "outstandingRecoveryAssetCount",
    "inputs": [],
    "outputs": [
      {
        "name": "count",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "outstandingRecoveryAssets",
    "inputs": [
      {
        "name": "offset",
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
        "name": "assets",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "nextOffset",
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
    "name": "previewIssueFromBasketExactIn",
    "inputs": [
      {
        "name": "maxAmountsIn",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "outputs": [
      {
        "name": "netCygldOut",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "protocolFeeCygld",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "amountsInExact",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "orderedBasketAssets",
        "type": "address[]",
        "internalType": "address[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "previewIssueFromBasketExactOut",
    "inputs": [
      {
        "name": "netCygldOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "protocolFeeCygld",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "amountsInExact",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "orderedBasketAssets",
        "type": "address[]",
        "internalType": "address[]"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "previewRebalanceSwapExactIn",
    "inputs": [
      {
        "name": "assetIn",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "assetOut",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "amountIn",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "amountOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "previewRedeemExactIn",
    "inputs": [
      {
        "name": "grossCygldIn",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "quote",
        "type": "tuple",
        "internalType": "struct ICoreRedemption.RedemptionQuote",
        "components": [
          {
            "name": "grossCygldIn",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "netCygldIn",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "protocolFeeCygld",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "outputs",
            "type": "tuple[]",
            "internalType": "struct ICoreRedemption.TokenAmount[]",
            "components": [
              {
                "name": "kind",
                "type": "uint8",
                "internalType": "enum ICoreRedemption.TokenKind"
              },
              {
                "name": "token",
                "type": "address",
                "internalType": "address"
              },
              {
                "name": "id",
                "type": "uint256",
                "internalType": "uint256"
              },
              {
                "name": "amount",
                "type": "uint256",
                "internalType": "uint256"
              }
            ]
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "previewRedeemExactOut",
    "inputs": [
      {
        "name": "minimumOutputs",
        "type": "tuple[]",
        "internalType": "struct ICoreRedemption.TokenMinimum[]",
        "components": [
          {
            "name": "kind",
            "type": "uint8",
            "internalType": "enum ICoreRedemption.TokenKind"
          },
          {
            "name": "token",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "id",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "minimumAmount",
            "type": "uint256",
            "internalType": "uint256"
          }
        ]
      }
    ],
    "outputs": [
      {
        "name": "quote",
        "type": "tuple",
        "internalType": "struct ICoreRedemption.RedemptionQuote",
        "components": [
          {
            "name": "grossCygldIn",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "netCygldIn",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "protocolFeeCygld",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "outputs",
            "type": "tuple[]",
            "internalType": "struct ICoreRedemption.TokenAmount[]",
            "components": [
              {
                "name": "kind",
                "type": "uint8",
                "internalType": "enum ICoreRedemption.TokenKind"
              },
              {
                "name": "token",
                "type": "address",
                "internalType": "address"
              },
              {
                "name": "id",
                "type": "uint256",
                "internalType": "uint256"
              },
              {
                "name": "amount",
                "type": "uint256",
                "internalType": "uint256"
              }
            ]
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "previewRedeemRecoveryShares",
    "inputs": [
      {
        "name": "asset",
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
        "name": "rawOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "rebalanceSwapExactIn",
    "inputs": [
      {
        "name": "assetIn",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "assetOut",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "amountIn",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "minAmountOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "amountOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "recoveryPool",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "viewData",
        "type": "tuple",
        "internalType": "struct IRecoveryTypes.RecoveryPoolView",
        "components": [
          {
            "name": "impaired",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "coreAttachedShares",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "externalShares",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "redeemableRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "cygldPerAssetRawFp18",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "cygldSupplyCap",
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
          },
          {
            "name": "shareDecimals",
            "type": "uint8",
            "internalType": "uint8"
          }
        ]
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "redeem",
    "inputs": [
      {
        "name": "grossCygldIn",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "result",
        "type": "tuple",
        "internalType": "struct ICoreRedemption.RedemptionQuote",
        "components": [
          {
            "name": "grossCygldIn",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "netCygldIn",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "protocolFeeCygld",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "outputs",
            "type": "tuple[]",
            "internalType": "struct ICoreRedemption.TokenAmount[]",
            "components": [
              {
                "name": "kind",
                "type": "uint8",
                "internalType": "enum ICoreRedemption.TokenKind"
              },
              {
                "name": "token",
                "type": "address",
                "internalType": "address"
              },
              {
                "name": "id",
                "type": "uint256",
                "internalType": "uint256"
              },
              {
                "name": "amount",
                "type": "uint256",
                "internalType": "uint256"
              }
            ]
          }
        ]
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "redeemRecoveryShares",
    "inputs": [
      {
        "name": "asset",
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
      }
    ],
    "outputs": [
      {
        "name": "rawOut",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "redemptionFeePpm",
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
    "name": "rehabilitateRecoveryAsset",
    "inputs": [
      {
        "name": "request",
        "type": "tuple",
        "internalType": "struct IRecoveryTypes.RecoveryRehabilitation",
        "components": [
          {
            "name": "impairedAsset",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "expectedBasketHash",
            "type": "bytes32",
            "internalType": "bytes32"
          },
          {
            "name": "minimumTotalPoolRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "minimumCoreRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "minimumExternalRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "resultingBasketAssets",
            "type": "address[]",
            "internalType": "address[]"
          },
          {
            "name": "resultingTargetsPpm",
            "type": "uint256[]",
            "internalType": "uint256[]"
          },
          {
            "name": "resultingGoldRefGramsFp18",
            "type": "uint256[]",
            "internalType": "uint256[]"
          }
        ]
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
    "name": "reserveCustodyStatus",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "status",
        "type": "tuple",
        "internalType": "struct IRecoveryTypes.ReserveCustodyStatus",
        "components": [
          {
            "name": "lifecycle",
            "type": "uint8",
            "internalType": "enum IRecoveryTypes.ReserveLifecycle"
          },
          {
            "name": "poolImpaired",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "redeemablePoolRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "coreAttachedShares",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "externalShares",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "exitEntitlementRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "liveBalanceAvailable",
            "type": "bool",
            "internalType": "bool"
          },
          {
            "name": "liveRawCustody",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "activeAvailableRaw",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "poolRawDeficit",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "exitEntitlementDeficitRaw",
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
    "name": "reserveLifecycle",
    "inputs": [
      {
        "name": "asset",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [
      {
        "name": "viewData",
        "type": "tuple",
        "internalType": "struct IRecoveryTypes.ReserveLifecycleView",
        "components": [
          {
            "name": "lifecycle",
            "type": "uint8",
            "internalType": "enum IRecoveryTypes.ReserveLifecycle"
          },
          {
            "name": "exitEntitlementRaw",
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
    "name": "safeBatchTransferFrom",
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
        "name": "ids",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "values",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "data",
        "type": "bytes",
        "internalType": "bytes"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "safeIssue",
    "inputs": [
      {
        "name": "netCygldOut",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "expectedOrderedBasketAssets",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "maxAmountsIn",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "outputs": [
      {
        "name": "protocolFeeCygld",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "amountsIn",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "safeRedeem",
    "inputs": [
      {
        "name": "grossCygldIn",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "expectedOutputs",
        "type": "tuple[]",
        "internalType": "struct ICoreRedemption.TokenMinimum[]",
        "components": [
          {
            "name": "kind",
            "type": "uint8",
            "internalType": "enum ICoreRedemption.TokenKind"
          },
          {
            "name": "token",
            "type": "address",
            "internalType": "address"
          },
          {
            "name": "id",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "minimumAmount",
            "type": "uint256",
            "internalType": "uint256"
          }
        ]
      }
    ],
    "outputs": [
      {
        "name": "result",
        "type": "tuple",
        "internalType": "struct ICoreRedemption.RedemptionQuote",
        "components": [
          {
            "name": "grossCygldIn",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "netCygldIn",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "protocolFeeCygld",
            "type": "uint256",
            "internalType": "uint256"
          },
          {
            "name": "outputs",
            "type": "tuple[]",
            "internalType": "struct ICoreRedemption.TokenAmount[]",
            "components": [
              {
                "name": "kind",
                "type": "uint8",
                "internalType": "enum ICoreRedemption.TokenKind"
              },
              {
                "name": "token",
                "type": "address",
                "internalType": "address"
              },
              {
                "name": "id",
                "type": "uint256",
                "internalType": "uint256"
              },
              {
                "name": "amount",
                "type": "uint256",
                "internalType": "uint256"
              }
            ]
          }
        ]
      }
    ],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "safeTransferFrom",
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
    "name": "setApprovalForAll",
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
    "name": "setBasket",
    "inputs": [
      {
        "name": "currentBasketHash",
        "type": "bytes32",
        "internalType": "bytes32"
      },
      {
        "name": "assets_",
        "type": "address[]",
        "internalType": "address[]"
      },
      {
        "name": "targetsPpm_",
        "type": "uint256[]",
        "internalType": "uint256[]"
      },
      {
        "name": "goldRefGramsFp18_",
        "type": "uint256[]",
        "internalType": "uint256[]"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setIssuanceFeePpm",
    "inputs": [
      {
        "name": "currentIssuanceFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "newIssuanceFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setMaxTotalSupply",
    "inputs": [
      {
        "name": "currentMaxTotalSupply",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "newMaxTotalSupply",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
  },
  {
    "type": "function",
    "name": "setRedemptionFeePpm",
    "inputs": [
      {
        "name": "currentRedemptionFeePpm",
        "type": "uint256",
        "internalType": "uint256"
      },
      {
        "name": "newRedemptionFeePpm",
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
    "name": "setTreasury",
    "inputs": [
      {
        "name": "currentTreasury",
        "type": "address",
        "internalType": "address"
      },
      {
        "name": "newTreasury",
        "type": "address",
        "internalType": "address"
      }
    ],
    "outputs": [],
    "stateMutability": "nonpayable"
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
    "name": "totalSupply",
    "inputs": [
      {
        "name": "shareId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "supply",
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
    "name": "treasury",
    "inputs": [],
    "outputs": [
      {
        "name": "",
        "type": "address",
        "internalType": "address payable"
      }
    ],
    "stateMutability": "view"
  },
  {
    "type": "function",
    "name": "unallowancedBalanceOf",
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
    "name": "uri",
    "inputs": [
      {
        "name": "shareId",
        "type": "uint256",
        "internalType": "uint256"
      }
    ],
    "outputs": [
      {
        "name": "",
        "type": "string",
        "internalType": "string"
      }
    ],
    "stateMutability": "view"
  }
] as const;

export const CORE_DIAMOND_FUNCTIONS = [
  {
    "selector": "0x00fdd58e",
    "signature": "balanceOf(address,uint256)",
    "facet": "recoveryShare",
    "scope": "product"
  },
  {
    "selector": "0x01ff572d",
    "signature": "MAX_FEE_PPM()",
    "facet": "controllerConfig",
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
    "selector": "0x04551e9d",
    "signature": "REDEMPTION_FEE_EXEMPT_ROLE()",
    "facet": "controllerConfig",
    "scope": "product"
  },
  {
    "selector": "0x06fdde03",
    "signature": "name()",
    "facet": "token",
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
    "selector": "0x0aa6220b",
    "signature": "rollbackDefaultAdminDelay()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x0e89341c",
    "signature": "uri(uint256)",
    "facet": "recoveryShareMetadata",
    "scope": "product"
  },
  {
    "selector": "0x0f9182e7",
    "signature": "effectiveCygldSupplyCap()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x14370f0c",
    "signature": "previewRebalanceSwapExactIn(address,address,uint256)",
    "facet": "rebalance",
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
    "selector": "0x2ab4d052",
    "signature": "maxTotalSupply()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x2eb2c2d6",
    "signature": "safeBatchTransferFrom(address,address,uint256[],uint256[],bytes)",
    "facet": "recoveryShare",
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
    "selector": "0x3221c094",
    "signature": "setIssuanceFeePpm(uint256,uint256)",
    "facet": "controllerConfig",
    "scope": "product"
  },
  {
    "selector": "0x32866daf",
    "signature": "issueRecoveryShares(address,address[],uint256[])",
    "facet": "recoveryShare",
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
    "selector": "0x3f4ba83a",
    "signature": "unpause()",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0x40c10f19",
    "signature": "mint(address,uint256)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x420394b2",
    "signature": "basketAssets()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x4211fe70",
    "signature": "unallowancedBalanceOf(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x4e1273f4",
    "signature": "balanceOfBatch(address[],uint256[])",
    "facet": "recoveryShare",
    "scope": "product"
  },
  {
    "selector": "0x5098fc00",
    "signature": "coreAttachedRecoveryAssets()",
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
    "selector": "0x53473ae0",
    "signature": "setBasket(bytes32,address[],uint256[],uint256[])",
    "facet": "basketAdmin",
    "scope": "product"
  },
  {
    "selector": "0x5a487e17",
    "signature": "basketGoldRefGramsFp18()",
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
    "selector": "0x5f8a5e47",
    "signature": "finalizeReserveInactivation((address,bytes32,address[],uint256[],uint256[]))",
    "facet": "reserveLifecycle",
    "scope": "product"
  },
  {
    "selector": "0x61d027b3",
    "signature": "treasury()",
    "facet": "lens",
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
    "selector": "0x69588208",
    "signature": "safeRedeem(uint256,(uint8,address,uint256,uint256)[])",
    "facet": "redemption",
    "scope": "product"
  },
  {
    "selector": "0x6bfe1c58",
    "signature": "burnRecoveryShares(address,address,uint256)",
    "facet": "recoveryShare",
    "scope": "product"
  },
  {
    "selector": "0x6f790d9e",
    "signature": "redeemRecoveryShares(address,uint256,address,uint256)",
    "facet": "recoveryPoolSettlement",
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
    "selector": "0x75deee16",
    "signature": "activateAsset((address,uint8,bytes32,uint256,address[],uint256[],uint256[]))",
    "facet": "reserveLifecycle",
    "scope": "product"
  },
  {
    "selector": "0x78bac762",
    "signature": "previewRedeemExactIn(uint256)",
    "facet": "preview",
    "scope": "product"
  },
  {
    "selector": "0x798e9658",
    "signature": "basketCygldPerUnitFp18()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x7a0ed627",
    "signature": "facets()",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0x7e435382",
    "signature": "reserveCustodyStatus(address)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0x7ecebe00",
    "signature": "nonces(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x8264ba8d",
    "signature": "outstandingRecoveryAssetCount()",
    "facet": "lens",
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
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x84ef8ffc",
    "signature": "defaultAdmin()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0x860ecd33",
    "signature": "beginReserveExit((address,bytes32,uint256,address[],uint256[],uint256[]))",
    "facet": "reserveLifecycle",
    "scope": "product"
  },
  {
    "selector": "0x87198cf2",
    "signature": "setMaxTotalSupply(uint256,uint256)",
    "facet": "controllerConfig",
    "scope": "product"
  },
  {
    "selector": "0x88cfce56",
    "signature": "safeWallet()",
    "facet": "pause",
    "scope": "base"
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
    "selector": "0x95d89b41",
    "signature": "symbol()",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0x9dc29fac",
    "signature": "burn(address,uint256)",
    "facet": "token",
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
    "selector": "0xa22cb465",
    "signature": "setApprovalForAll(address,bool)",
    "facet": "recoveryShare",
    "scope": "product"
  },
  {
    "selector": "0xa3246ad3",
    "signature": "getRoleMembers(bytes32)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xa7a19e71",
    "signature": "issuanceFeePpm()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xa9059cbb",
    "signature": "transfer(address,uint256)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xadfca15e",
    "signature": "facetFunctionSelectors(address)",
    "facet": "loupe",
    "scope": "base"
  },
  {
    "selector": "0xadfe0870",
    "signature": "setTreasury(address,address)",
    "facet": "controllerConfig",
    "scope": "product"
  },
  {
    "selector": "0xb2538ec2",
    "signature": "basketConfigHash()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xb3fd7741",
    "signature": "basketTargetsPpm()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xb8b17531",
    "signature": "setSafeWallet(address,address)",
    "facet": "pause",
    "scope": "base"
  },
  {
    "selector": "0xba588430",
    "signature": "previewRedeemRecoveryShares(address,uint256)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xbd85b039",
    "signature": "totalSupply(uint256)",
    "facet": "recoveryShare",
    "scope": "product"
  },
  {
    "selector": "0xc6122eb7",
    "signature": "reserveLifecycle(address)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xc81212d5",
    "signature": "cygldRefGramsFp18()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xc8ba2f6d",
    "signature": "previewRedeemExactOut((uint8,address,uint256,uint256)[])",
    "facet": "preview",
    "scope": "product"
  },
  {
    "selector": "0xca15c873",
    "signature": "getRoleMemberCount(bytes32)",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xcc649f16",
    "signature": "recoveryPool(address)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xcc8463c8",
    "signature": "defaultAdminDelay()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xcc872b66",
    "signature": "issue(uint256)",
    "facet": "issuance",
    "scope": "product"
  },
  {
    "selector": "0xcdffacc6",
    "signature": "facetAddress(bytes4)",
    "facet": "loupe",
    "scope": "base"
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
    "selector": "0xd602b9fd",
    "signature": "cancelDefaultAdminTransfer()",
    "facet": "access",
    "scope": "base"
  },
  {
    "selector": "0xdb006a75",
    "signature": "redeem(uint256)",
    "facet": "redemption",
    "scope": "product"
  },
  {
    "selector": "0xdb129a1c",
    "signature": "previewIssueFromBasketExactIn(uint256[])",
    "facet": "preview",
    "scope": "product"
  },
  {
    "selector": "0xdd62ed3e",
    "signature": "allowance(address,address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xdf809d9f",
    "signature": "activateRecovery((address,uint8,bytes32,uint256,address[],uint256[],uint256[],uint256))",
    "facet": "recoveryAdmin",
    "scope": "product"
  },
  {
    "selector": "0xe144eeff",
    "signature": "safeIssue(uint256,address[],uint256[])",
    "facet": "issuance",
    "scope": "product"
  },
  {
    "selector": "0xe5b323f3",
    "signature": "rebalanceSwapExactIn(address,address,uint256,uint256)",
    "facet": "rebalance",
    "scope": "product"
  },
  {
    "selector": "0xe8a3d485",
    "signature": "contractURI()",
    "facet": "recoveryShareMetadata",
    "scope": "product"
  },
  {
    "selector": "0xe985e9c5",
    "signature": "isApprovedForAll(address,address)",
    "facet": "recoveryShare",
    "scope": "product"
  },
  {
    "selector": "0xeb33347d",
    "signature": "setRedemptionFeePpm(uint256,uint256)",
    "facet": "controllerConfig",
    "scope": "product"
  },
  {
    "selector": "0xebdd2f41",
    "signature": "allowanceExposure(address)",
    "facet": "token",
    "scope": "product"
  },
  {
    "selector": "0xec4661fb",
    "signature": "rehabilitateRecoveryAsset((address,bytes32,uint256,uint256,uint256,address[],uint256[],uint256[]))",
    "facet": "recoveryAdmin",
    "scope": "product"
  },
  {
    "selector": "0xf1f487d5",
    "signature": "previewIssueFromBasketExactOut(uint256)",
    "facet": "preview",
    "scope": "product"
  },
  {
    "selector": "0xf242432a",
    "signature": "safeTransferFrom(address,address,uint256,uint256,bytes)",
    "facet": "recoveryShare",
    "scope": "product"
  },
  {
    "selector": "0xf9cdd808",
    "signature": "outstandingRecoveryAssets(uint256,uint256)",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xfd0602f1",
    "signature": "redemptionFeePpm()",
    "facet": "lens",
    "scope": "product"
  },
  {
    "selector": "0xfe90b33d",
    "signature": "finalizeZeroEntitlementRecovery(address)",
    "facet": "recoveryAdmin",
    "scope": "product"
  }
] as const;

export const CORE_DIAMOND_INTERFACE_ID = "0x1e260249" as const;

export const CORE_DIAMOND_ERC165_ADVERTISED = false as const;
