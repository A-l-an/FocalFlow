# FocalFlow Android / TalkBack companion

This is the complete Google TalkBack-derived Gradle project with FocalFlow capture,
protocol, mapping and focus-filtering changes. The person continues to navigate
and activate controls. Start at the [root README](../README.md) for integrated
setup, licensing status and evidence limits.

| Path | Role |
| --- | --- |
| [TalkBackService.java](talkback/src/main/java/com/google/android/accessibility/talkback/TalkBackService.java) | Accessibility events, capture scheduling and owned main-queue recovery/exit callbacks |
| [utils accessibility package](utils/src/main/java/com/google/android/accessibility/utils) | PcConnectionManager, VirtualTreeBuilder/Manager/Validator, NodeMappingManager, FocusProxy, context and transport state |
| [contextmenu](talkback/src/main/java/com/google/android/accessibility/talkback/contextmenu), [gesture](talkback/src/main/java/com/google/android/accessibility/talkback/gesture) | Existing menu/gesture integration and pause/resume |
| [talkback](talkback), [utils](utils), [braille](braille), [proguard](proguard) | Reader, shared utilities, native/braille modules and build integration |
| [tests](tests) | Desktop Java harnesses, synthetic fixtures, platform stubs and real Python wire/admission bridges |

Production Android source is unchanged by monorepo integration. It retains the
`com.android.talkback` application ID, visible FocalFlow labels, strict SESSION_READY
handshake, local preconnection waiting, postconnection service-exit path and CONTENT
event continuity. The selected retiring-capture-after-EOF issue remains open.

For full checks, run the root `scripts/check-offline.sh` with existing Python,
JDK16, org.json:20180813 and Android34 android.jar paths. Direct commands from this
component directory are:

```sh
python3.8 -B tests/check_logging_wiring.py
python3.8 -B tests/run_sensitive_logging_tests.py --json-jar /path/to/json-20180813.jar --java-home /path/to/jdk16 --android-jar /path/to/android-34/android.jar --backend ../backend --python38 /path/to/python3.8
```

Tests use platform stubs/extracted Service bodies. They do not run an Android
Looper, load an APK or establish real speech/gesture/device behavior. Full Gradle
build instructions are in [setup](../docs/setup.md#android-build); source resources,
braille/native code and the wrapper JAR remain included. APKs, caches, local SDK
configuration and signing material are not exported.

Phone-first waiting, a correlated ACK and desktop EOF shutdown had targeted device
evidence at the selected Android checkpoint; no new device acceptance is claimed
for this directory migration and no complete ordering flow is claimed. Root
architecture/mapping/logging notes retained here are historical background;
[architecture](../docs/architecture.md), [protocol](../docs/protocol-v1.md) and
[known issues](../docs/known-issues.md) describe the selected maintained baseline.

Preserve [LICENSE](LICENSE), [THIRD_PARTY.md](THIRD_PARTY.md), vendored notices and
file headers. These do not resolve licensing for the entire FocalFlow project.

## Research correspondence, attribution and maintenance

This tree retains Google's TalkBack and separately licensed upstream/native
components. Read THIRD_PARTY.md and the project-level licensing status before
redistribution. The selected integration is not identified as the study evaluation
commit; paper bibliographic metadata and rights are not inferred here.
