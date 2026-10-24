# Selected contract release ABIs

These JSON files are the selected Core and Governance Protocol release ABIs
consumed by this Backend. `../abi-source.json` records each artifact's exact
Protocol path and producer commit. Core includes the distinct CYGLD supply,
ordinary reserve and Core-attached recovery-share shortage errors. Governance
retains its original selected ABI from Protocol commit
`d4f877ecf1480d68a8bccc5494cc0b40b4ced759`.

The existing ABI generator reads these bundled release files, so regenerating or
checking the Backend does not require a sibling Protocol checkout or its private
historical Git objects. Generated TypeScript modules preserve the selected ABI's
interface metadata. The retained Governance identity does not claim that its old
source commit belongs to the new public history.

On an actual contract release change, explicitly replace the selected JSON files
and update that artifact's record in `abi-source.json` to its exact producer, then run
`node scripts/generate-contract-abis.mjs` and its existing `--check` mode. The
current Protocol release must not be substituted solely to refresh a Git ID,
because its Governance ABI differs from this released Backend baseline.
