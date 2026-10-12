# Licensing status — private candidate

A project-wide license remains a rights-holder decision. The imported Python
backend has no project license grant file; none is inferred from dependency terms
or the Android component. Contributor/institutional rights and the intended
license for original FocalFlow code remain pending.

## Preserved and completed notices

The Android [Apache-2.0 LICENSE](../android/LICENSE), file headers and the dated
[THIRD_PARTY inventory](../android/THIRD_PARTY.md) are unchanged. The inventory
records the 2026-09-26 snapshot and is retained as historical evidence; its prior
missing-text/resource-status entries are updated by the facts below.

Full LGPL2.1, GPL2, GPL3 and LGPL3 terms are now included in
[LICENSES](../LICENSES/README.md), with component scopes, source URLs and exact
copied-file SHA-256 hashes. Legal text is copied verbatim; Linux SPDX/usage metadata
is excluded from the GPL2 text. These are terms for separately licensed components,
not a blanket license or a new grant for FocalFlow/backend source.

## Resource and bootstrap provenance

A byte comparison matched **65 static resources** (images, earcons, MIDI and font)
to Google's official `google/talkback` commit
[`26a27dc009d5b3605e744222541f045a3c24e038`](https://github.com/google/talkback/tree/26a27dc009d5b3605e744222541f045a3c24e038),
whose version file declares `TfPu_release_15_1`. This identifies their upstream
bytes; individual notices/terms still apply. The resources and their headers are
preserved. No personal recording or generated APK was added.

The retained Gradle wrapper bootstrap JAR has SHA-256
`7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172`,
which exactly matches the
[official Gradle 8.14.3 wrapper-JAR checksum](https://services.gradle.org/distributions/gradle-8.14.3-wrapper.jar.sha256).
Wrapper bootstrap **8.14.3** and the requested Gradle distribution **7.6.4** are
separate facts: wrapper properties still select the 7.6.4 distribution. The JAR
and distribution URL are unchanged. The dated inventory's earlier unresolved
wrapper checksum entry is superseded by this exact upstream match.

## Remaining publication decisions

Original-code licensing and applicable rights, mixed table/font terms, native
linking/source/relinking scope and final package notice delivery remain distinct
questions. See [backend/THIRD_PARTY.md](../backend/THIRD_PARTY.md) as well. Model
weights, participant data, papers, private config and old Git history are not
included. No project-wide license or public release clearance is asserted.
