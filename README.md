# FocalFlow

FocalFlow helps blind and low vision people explore multi-step mobile tasks.
Its Android companion extends Google TalkBack; a Python backend uses the task,
accessibility tree and screenshot to select relevant regions. The person keeps
control of navigation and activation on the phone.

[中文说明](README.zh-CN.md) · [Architecture](docs/architecture.md) ·
[Setup](docs/setup.md) · [Protocol](docs/protocol-v1.md)

## What's included

```text
backend/   Python listener, state machine, prompts, providers and speech
android/   Complete TalkBack-derived Gradle project, braille modules and resources
scripts/   Offline demo/checks and bounded macOS manual launcher
docs/      Setup, architecture, protocol, source baseline and known issues
LICENSES/  Full terms for separately licensed GNU components
```

TCP on localhost port 9998 carries controls/results; ADB supplies the tree and
screenshot. Generated speech and microphone/Whisper transcription run on the PC;
TalkBack speech runs on the phone. See the [architecture](docs/architecture.md).
The Android application ID stays `com.android.talkback`.

## Install and try the offline demo

Python 3.8.19 and macOS are the reference environment. From the repository root:

```sh
python3.8 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-offline.txt
export FOCALFLOW_PYTHON="$(pwd)/.venv/bin/python"
./scripts/offline-demo.sh
./scripts/check-offline.sh
```

The demo uses a fictional tree, a tiny white image and fixed responses. It runs
the production flow and reports `state=waiting` and `external_calls=0` without a
phone, credentials, provider calls, audio hardware or model download. The five
pinned direct dependencies are the offline setup; do not install the large legacy
research requirements list by default. A fresh venv installation and offline checks
passed on the reference macOS host; this is not fresh-OS or live validation.

`check-offline.sh` also runs the launcher selftest and Android static checks.
To include full Java/Python bridge checks, set `FF_JAVA_HOME`, `FF_JSON_JAR` and
`FF_ANDROID_JAR` to existing tools as shown in [verification](docs/verification.md).
Optional sounddevice-source tests skip when that package is absent.

## Build the Android app

Prepare Java 16, Android SDK34 and NDK25.2.9519653; configure your SDK through
`android/local.properties` or your Android toolchain. The project declares Gradle
7.6.4, AGP7.2.2 and Kotlin1.8.0. The normal build can download declared dependencies:

```sh
cd android
./gradlew --no-daemon --console=plain :assemblePhoneDebug
cd ..
```

APK output is under `android/build/outputs/apk/phone/debug/`. Existing-cache offline
build instructions are in [setup](docs/setup.md#android-build). The integrated source
[passed an offline APK build](docs/verification.md#android-monorepo-build) using
existing caches; the APK was not installed. Use a dedicated test phone; the app ID
may conflict with an installed reader's signature.

## Run the phone-first burger flow on macOS

The live launcher needs ADB, microphone/output permissions, cached Whisper `base`
weights and the extra [live dependencies](docs/setup.md#python-environments).
Prepare a private mode-600 config outside the repository from the
[field example](backend/tools/manual_testing/providers.env.example); placeholders
are invalid. The selected chat configuration uses `gpt-6-luna`; live requests can
incur provider charges. The launcher inherits your proxy/CA settings.

```sh
export FOCALFLOW_CONFIG=/absolute/path/outside/repository/providers.env
export FOCALFLOW_ADB=/absolute/path/to/adb
# Enable FocalFlow on the phone first, then start the computer:
./scripts/run.sh
```

The phone initially waits with filtering inactive. A matching `SESSION_READY`
handshake is required before capture; then leave settings and navigate the task
app yourself. The normal entry uses the burger preset and runs until you stop it,
without session-wide time or chat/TTS call caps. Each analysis request retains its
120-second deadline. For a bounded test round, use `./scripts/run-manual.sh`;
it retains **24 chat / 12 TTS / 600 second** limits. Direct `backend/run.py` retains
its hospital preset default. Use `./scripts/run.sh --check` for an offline entry
check without phone, credentials or API calls.

Use **Ctrl+C** to stop and check that FocalFlow is off on the phone. The TalkBack
menu offers **Use standard browsing (pause AI)** and **Enable AI filtering**.
If USB cleanup is unavailable, switch FocalFlow off in system Accessibility
settings. Round logs are private in `~/Library/Application Support/FocalFlow` by
default; [setup](docs/setup.md) explains path overrides and data handling.

## Current status

The observed merchant-activation stall and paused startup/EOF issues remain in
[known issues](docs/known-issues.md); a complete ordering flow and paper-result
reproduction are not established. [Offline verification](docs/verification.md)
and [source baseline](docs/source-baseline.md) describe the tested scope.

This IMWUT26 source release licenses original FocalFlow code and documentation
under [Apache-2.0](LICENSE). Third-party terms and notices remain applicable;
see [licensing scope](docs/licensing-status.md) and [LICENSES](LICENSES/README.md).
