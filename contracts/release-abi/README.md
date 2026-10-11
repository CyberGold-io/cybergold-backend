# Released contract ABI baseline

These two fixed JSON files preserve the Protocol release ABI consumed by this
Backend before the public source history began. Their original producer identity
is retained in `../abi-source.json`: Protocol commit
`d4f877ecf1480d68a8bccc5494cc0b40b4ced759`, paths
`generated/abi/CoreDiamond.json` and `generated/abi/GovernanceDiamond.json`.

The existing ABI generator reads these bundled release files, so regenerating or
checking the Backend no longer requires the private historical Git object. The
generated TypeScript modules retain their original bytes and interface metadata.
This records the selected consumer ABI; it does not claim that the old source
commit belongs to the new public history.

On an actual contract release change, explicitly replace the selected JSON files
and update `abi-source.json` to that exact producer release, then run
`node scripts/generate-contract-abis.mjs` and its existing `--check` mode. The
current Protocol release must not be substituted solely to refresh a Git ID,
because its Governance ABI differs from this released Backend baseline.
