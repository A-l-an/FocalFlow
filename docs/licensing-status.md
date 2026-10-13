# Licensing and source release scope

Original FocalFlow source code and documentation are licensed under **Apache-2.0**.
The complete terms are in the root [LICENSE](../LICENSE), with distribution scope
in [NOTICE](../NOTICE).

Existing third-party files, GNU components, fonts and resources retain their own
applicable terms and copyright notices. The root Apache license does not replace
or override them.

## Preserved and completed notices

The Android [Apache-2.0 LICENSE](../android/LICENSE), file headers and the dated
[THIRD_PARTY inventory](../android/THIRD_PARTY.md) are unchanged. The inventory
records the 2026-09-26 snapshot and is retained as historical evidence; its prior
missing-text/resource-status entries are updated by the facts below.

Full LGPL2.1, GPL2, GPL3 and LGPL3 terms are now included in
[LICENSES](../LICENSES/README.md), with component scopes, source URLs and exact
copied-file SHA-256 hashes. Legal text is copied verbatim; Linux SPDX/usage metadata
is excluded from the GPL2 text. These are terms for separately licensed components,
not a blanket Apache grant for the GNU/font/resource tree.

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

## Source-only distribution boundaries

This release includes source, required upstream resources and the wrapper bootstrap
JAR. It does not include an APK, model weights, participant data, papers, private
config or old Git history. The selected paired source snapshot is confirmed in
[source baseline](source-baseline.md); the documented difference from the last
actual Luna startup variant is retained.

Per-file table/font declarations remain as provided. External dependencies,
provider services and any separately obtained models have their own terms;
requirements/model names are not grants to redistribute those materials. The dated
[backend inventory](../backend/THIRD_PARTY.md) describes an earlier snapshot and
is linked to this current license decision.

A future binary/package distributor must satisfy the applicable native-linking,
source/relinking and notice-delivery requirements of included third-party components.
Those package-specific obligations are distinct from this source-only release.
Existing copyright headers and third-party legal texts are retained unchanged.
