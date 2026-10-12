# Selected source baseline

This monorepo imports Git source trees without their history, then overlays 34
hash-verified frozen files from a paired offline-tested snapshot:

| Component | Base commit | Imported source files |
| --- | --- | --- |
| Python backend | `314d3b53646dbada806114c3cca442cad34e780d` | 54 (51 tracked + 3 frozen new files) |
| Android | `162abc52b92175ba786a44f0ad6771bb200303f6` | 3759 (3757 tracked + 2 frozen new files) |

The overlay contains 14 backend and 20 Android files. Its hashes are recorded in
[source-baseline.json](source-baseline.json). Original source modes, resources,
upstream license files and headers are retained. Directory/configuration changes
for the monorepo are described separately in verification; they are not part of
the historical baseline hash claims.

## Relationship to the last device run

The selected Android PcConnectionManager hash is
`7a900cd030a93f05a55023df5667b004b622756dae0a6dcefd85268d62beb9f6`.
It corresponds to the APK used in the recent phone-first/readiness trial (APK
SHA-256 `af8f5e97b9495ffc33afecf082e5149a421f779f915ea10499d41c46f5ee4712`).
The APK itself is not bundled.

The selected frozen backend `run.py` hash is
`ab8de3254b53e316042e31619c431a8f3179312570bbc155168b0c246c822c5a`.
The later real Luna trial used startup variant
`9a7cf1ea96975e3669a83189480ac7323db9c47a9284c9b113ecd4c4d6cb4bbd`.
Those are different bytes. The function-level comparison differs only in
`UIListener.run_server` (plus its supporting top-level errno import): the later
variant contains paused socket-restart/error-reporting changes. This monorepo
selects the earlier paired offline-validated snapshot and excludes those unfinished
changes and their partial restart test. Business stage/prompt/model functions in
that comparison are unchanged, but no exact-last-run-source equivalence is claimed.

Selected sibling runtime and launcher hashes before mechanical relocation:

- `live_backend.py`: `4b176f8b93ed93e1af9b863a177756681f9239c943b106ed89b3ff97917a0eaf`
- `manual_test.py`: `517b131c53d68b91052d05b862fcf6d622d803623eae4cca77c22be8d6824e43`

The runtime hash pin is updated when its local paths change. Prompt fixtures,
models, task defaults, protocol v1 and caps are preserved. Normal CONTENT events
do not cancel active work. This baseline is not identified as the paper evaluation
commit. The export includes synthetic fixtures and Android source/build resources;
it excludes ignored user/research data, model weights, caches, config, signing
material, APKs, private incident evidence and old Git history.
