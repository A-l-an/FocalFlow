# Third-party provenance and redistribution inventory

This is an offline, static inventory as of 2026-09-26, inspected at commit
`586db40f53b7fa3ec6a6a800f389086b3c54edb6`. It records declarations in the local
source; it is not a legal review or publication approval. File/line references
describe that snapshot. The existing [LICENSE](LICENSE) and upstream file headers
are retained unchanged. **This document does not apply one license to all files.**

## Copied source and build integration

| Material | Local evidence | Confirmed declaration and gaps |
| --- | --- | --- |
| Google TalkBack / Android accessibility source | [README attribution](README.md#research-correspondence-attribution-and-maintenance); [TalkBackService.java:2](talkback/src/main/java/com/google/android/accessibility/talkback/TalkBackService.java#L2); [LICENSE:2](LICENSE#L2) | The README identifies Google's TalkBack; the service retains Android Open Source Project attribution and an Apache-2.0 header. The root contains the full Apache-2.0 text. This is source in the repository, not merely an external TalkBack dependency. |
| TalkBack version and local integration | [version.gradle:1](version.gradle#L1); [PcConnectionManager.java:28](utils/src/main/java/com/google/android/accessibility/utils/PcConnectionManager.java#L28) | Local build label is `TfPu_release_15_1`; the tree includes PC-connection integration. The label is not a verified upstream tag/commit. Exact upstream provenance, the complete local-change list, contributor rights, and required modified-file notices remain to be established. |
| BRLTTY vendored source | [config.h:6](braille/brltty/src/phone/jni/brlttywrapper/third_party/brltty/config.h#L6), [11](braille/brltty/src/phone/jni/brlttywrapper/third_party/brltty/config.h#L11), [34](braille/brltty/src/phone/jni/brlttywrapper/third_party/brltty/config.h#L34) | The BRLTTY Developers attribution; header declares LGPL-2.1-or-later and refers to `LICENSE-LGPL`. Local version macro says `6.6`, with project URL in the same header. The exact upstream commit and local modifications are not verified; the referenced license file is absent from the tracked candidate. |
| GPL-declared BRLTTY-related files | [braille/brltty/src/phone/jni/Android.mk:1](braille/brltty/src/phone/jni/Android.mk#L1); [vstp.h:2](braille/brltty/src/phone/jni/brlttywrapper/third_party/brltty/Drivers/Braille/VisioBraille/vstp.h#L2), [vstp_main.c:2](braille/brltty/src/phone/jni/brlttywrapper/third_party/brltty/Drivers/Braille/VisioBraille/vstp_main.c#L2), [vstp_transfer.c:2](braille/brltty/src/phone/jni/brlttywrapper/third_party/brltty/Drivers/Braille/VisioBraille/vstp_transfer.c#L2) | The makefile retains Google Inc. attribution; the VisioBraille files retain S&S, Samuel Thibault, and Sébastien Hinderer attribution. Each declares GPL-2.0-or-later. A BRLTTY-wide LGPL label would miss these files. Full GPL text and distribution scope require verification. |
| liblouis vendored source | [lou_translateString.c:1](braille/translate/src/phone/jni/third_party/liblouis/liblouis/lou_translateString.c#L1), [14](braille/translate/src/phone/jni/third_party/liblouis/liblouis/lou_translateString.c#L14); [config.h:477](braille/translate/src/phone/jni/third_party/liblouis/liblouis/config.h#L477) | Header preserves BRLTTY Team, ViewPlus Technologies, JJB Software, Mike Gray, and Davy Kager attribution and declares LGPL-2.1-or-later. Local version macro says `3.26.0`; this is not verification of an upstream commit. No complete LGPL text is tracked. |
| Native linking declarations | [translation Android.mk:26](braille/translate/src/phone/jni/Android.mk#L26), [30](braille/translate/src/phone/jni/Android.mk#L30), [42](braille/translate/src/phone/jni/Android.mk#L42); [BRLTTY Android.mk:260](braille/brltty/src/phone/jni/Android.mk#L260) | Build files reference vendored native sources, shared-library builds, and whole-static-library inputs. The actual linked/package contents and any required source/relinking materials were not established by this static check. No binary-compliance conclusion is made. |

## Tables and non-code resources

| Material | Local evidence | Confirmed declaration and gaps |
| --- | --- | --- |
| liblouis translation tables (238 tracked files) | [table packaging:19](braille/translate/build.gradle#L19); [Es-Es-G0.utb:14](braille/translate/src/phone/tables/Es-Es-G0.utb#L14), [19](braille/translate/src/phone/tables/Es-Es-G0.utb#L19); [countries.cti:2](braille/translate/src/phone/tables/countries.cti#L2) | Build task creates a table ZIP. Table notices vary: the Spanish table names José Enrique Fernández del Campo and Juan Carlos Buño Suárez and declares LGPL-3.0-or-later. `countries.cti` declares LGPL-2.1-or-later at lines 4–7 but also names GPL and missing `COPYING` at lines 17–19. Preserve each header; the latter's intended terms and complete table-by-table scope remain unresolved. Do not assign all tables the library's LGPL-2.1 label. |
| BRLTTY key tables (190 tracked files) | [key-table packaging:21](braille/brltty/build.gradle#L21); [abt_basic.kti:5](braille/brltty/src/phone/tables/al/abt_basic.kti#L5), [10](braille/brltty/src/phone/tables/al/abt_basic.kti#L10) | Build task creates a key-table ZIP. The sampled header names The BRLTTY Developers and LGPL-2.1-or-later, referencing missing `LICENSE-LGPL`. Preserve individual notices; this is not a full rights determination for every table. |
| UBraille font | [README.UBraille:1](braille/brltty/src/phone/jni/brlttywrapper/third_party/brltty/Drivers/Braille/XWindow/README.UBraille#L1); [UBraille.ttf](braille/brltty/src/phone/jni/brlttywrapper/third_party/brltty/Drivers/Braille/XWindow/UBraille.ttf) | README names Vyacheslav Dikonov and a yudit.org download location. Font `name` table, name ID 0, says it was created by Vyacheslav Dikonov and is “Free to use and distribute.” Name ID 5 says `001.000`. No separate complete font license is tracked; modification rights and exact upstream provenance are not inferred from that short statement. |
| Image and sound assets | [talkback/src/main/res](talkback/src/main/res), [utils/src/main/res](utils/src/main/res), [braille/common/src/phone/res](braille/common/src/phone/res), [braille/brailleime/src/phone/res](braille/brailleime/src/phone/res), [braille/brailledisplay/src/phone/res](braille/brailledisplay/src/phone/res) | Candidate contains 38 PNGs, one JPEG, 23 OGGs, and two MIDI files. Examples include [onboarding_sample_image.jpg](talkback/src/main/res/drawable/onboarding_sample_image.jpg), [focus.ogg](talkback/src/main/res/raw/focus.ogg), and [display_connected.mid](braille/common/src/phone/res/raw/display_connected.mid). Individual creator/source/redistribution terms have not been established; filenames or neighboring source headers do not settle their rights. No media was played. |
| Gradle wrapper binary and scripts | [gradle-wrapper.jar](gradle/wrapper/gradle-wrapper.jar), [gradlew:4](gradlew#L4), [gradlew.bat:2](gradlew.bat#L2), [wrapper properties:3](gradle/wrapper/gradle-wrapper.properties#L3) | Scripts have original-author attribution and Apache-2.0 headers; the JAR contains `META-INF/LICENSE` with Apache-2.0 text and identifies itself as Gradle Wrapper in `META-INF/MANIFEST.MF`. Properties request Gradle `7.6.4`. This distribution setting does not prove the JAR's build version or integrity; upstream checksum/provenance has not been verified. |

No other binary file types were found by the tracked-file NUL-byte scan at the
inspected commit. This is not a guarantee of complete asset/license coverage.
Excluded local files, Git history, research data, paper files, downloaded models,
and future generated packages are outside this inventory and need their own
permission/privacy checks if proposed for distribution.

## External build dependencies

[shared.gradle:53](shared.gradle#L53) declares Guava, ML Kit text recognition,
Material Components, Google Play Core, AndroidX libraries, Checker Framework,
AutoValue, javax.annotation, Wear libraries, ZXing, Joda-Time, and Volley.
[build.gradle:16](build.gradle#L16) declares Kotlin `1.8.0`, AspectJ tools
`1.8.1`, and Android Gradle Plugin `7.2.2`. The exact local declarations are the
source of truth; notably [shared.gradle:90](shared.gradle#L90) requests Volley
`1.0.+`, which does not fix a resolved version.

No dependency resolution or build ran for this inventory. These declarations
are not evidence of the final dependency graph, bundled artifacts, or their
license terms. Record resolved artifacts and applicable notices before packaging.
[build.gradle:50](build.gradle#L50) excludes a resource named `LICENSE` from
packaging; inspect the resulting package and notice delivery before release.
That rule was not changed, and its presence alone does not establish which
notices would be omitted in an actual build.

## Publication prerequisites still open

- Recover and verify the precise TalkBack, BRLTTY, and liblouis upstream
  revisions, local modifications, and applicable contributor/institutional
  authorization. Preserve existing attribution and determine modified-file
  notices from that comparison. The root Apache license does not settle the
  provenance or rights of every local contribution.
- Obtain the applicable full GNU license texts from verified upstream material;
  the tracked candidate has no `LICENSE-LGPL`, `COPYING`, or full GPL/LGPL text.
  Resolve the mixed notice in `countries.cti` and table-specific terms. No
  substitute license has been invented or downloaded in this step.
- Establish the intended source and binary distribution scope, native-linking
  obligations, resource permissions, font scope, and dependency notice delivery.
- Keep the separate sensitive-data/history publication blockers in force.

These items block related publication decisions. They do not block authorized
local engineering, and this inventory does not replace a rights-holder decision.
