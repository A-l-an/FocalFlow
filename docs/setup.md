# Setup and operator-controlled paths

Start with the synthetic commands in the root README. No credentials, ADB device,
Whisper download or audio hardware is required for those commands. Live execution
is a separate, potentially billed operation with private screen/speech content.

## Python environments

The measured interpreter is CPython 3.8.19 on macOS arm64. The five direct offline
dependencies are pinned in `backend/requirements-offline.txt`; this is not a full
transitive lock. A normal online setup from the repository root is:

```sh
python3.8 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-offline.txt
export FOCALFLOW_PYTHON="$(pwd)/.venv/bin/python"
./scripts/offline-demo.sh
```

This procedure passed in a fresh Python venv on the reference macOS host: the five
direct dependencies and their transitives installed successfully, and the demo,
145-test suite (two optional sounddevice-source checks skipped), launcher selftest
and 21 static checks passed. Java/bridge tools were not supplied in that venv run
and were explicitly skipped. This does not establish fresh-OS or live setup.
An existing approved local wheelhouse can be used separately:

```sh
python3.8 -m pip install --no-index --find-links /path/to/local/wheels -r backend/requirements-offline.txt
```

The fresh-venv check is limited to offline Python/static entries. Do not install the 165-entry legacy
research requirements list merely to run the demo. Live speech also uses numpy
1.24.4, sounddevice 0.5.1, soundfile 0.13.1, scipy 1.10.0, torch 2.4.1 and
openai-whisper 20240930, plus cached Whisper `base` weights. Native microphone and
speaker permissions are required. Existing macOS cue paths and microphone-name
preference are retained. No weights are included or downloaded by offline checks.

## Manual launcher configuration

Prepare your own config outside the repository and set its permission to 600.
[The example](../backend/tools/manual_testing/providers.env.example) lists exactly
the seven fields accepted by the bounded runtime:

| Field | Purpose |
| --- | --- |
| `FOCALFLOW_CHAT_API_URL` | Complete chat-completions URL |
| `FOCALFLOW_CHAT_API_TOKEN` | Private chat credential |
| `FOCALFLOW_CHAT_MODEL` | Explicit selected model ID |
| `OPENAI_BASE_URL` | Existing runtime requires `https://api.openai.com/v1` |
| `OPENAI_API_KEY` | Private OpenAI TTS credential |
| `OPENAI_TTS_MODEL` | Existing runtime requires `gpt-4o-mini-tts` |
| `OPENAI_TTS_VOICE` | Existing runtime requires `nova` |

The selected official chat model is `gpt-6-luna`. Exactly that ID uses
`max_completion_tokens=2048` and `reasoning_effort=none`, omitting legacy
`temperature`/`seed`; other models retain their original payload fields. Text and
image messages remain unchanged. This is configuration/payload behavior, not a
live availability or pricing guarantee.

Do not put credentials into commands, issues or tracked files. The placeholders
are invalid. Set a path to an independently prepared file:

```sh
export FOCALFLOW_CONFIG=/absolute/path/outside/repository/providers.env
export FOCALFLOW_PYTHON=/absolute/path/to/python3.8
export FOCALFLOW_ADB=/absolute/path/to/adb
./scripts/run-manual.sh
```

| Setting | Default / scope |
| --- | --- |
| `FOCALFLOW_PYTHON` | Current Python interpreter in launcher; root shell wrappers use `python3` when unset |
| `FOCALFLOW_ADB` | `adb` found on PATH; no author-specific executable path |
| `FOCALFLOW_CONFIG` | `~/.config/focalflow/providers.env`; launcher/runtime read only during live startup |
| `FOCALFLOW_STATE_DIR` | `~/Library/Application Support/FocalFlow`; contains private per-round manual logs |
| `FOCALFLOW_RUN_DIR` | Standalone runtime storage; normal launcher sets a unique round directory directly |
| `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, `NO_PROXY`, CA environment | Inherited from the operator without a forced personal proxy |

The config is not automatically sourced into the shell. The strict runtime parser
accepts only its seven fields. The original `backend/.env.example` describes the
separate direct/legacy entries; those use explicitly exported variables rather
than this manual config file.

Before backend import, the launcher makes a bounded unauthenticated GET to the
configured chat endpoint through the same proxy/CA route, without implicit netrc
credentials or response-body reading. Any HTTP response proves reachability only;
it does not validate API keys/model/quota. A failed probe stops the round and tries
safe phone cleanup. The offline checks substitute this boundary and make no probe.

## Android build

The full upstream Gradle project is inside `android/`, including braille/native
modules and required source resources. Use Java 16, SDK 34/build tools and NDK
25.2.9519653 with the declared dependencies cached. Keep `local.properties`, your
Gradle cache, signing files and generated APKs untracked.

```sh
cd android
./gradlew --offline --no-daemon --console=plain -Pandroid.builder.sdkDownload=false :assemblePhoneDebug
```

The root Android project is the application; `talkback` is a library. The phone
debug APK is produced under `android/build/outputs/apk/phone/debug/` relative to
the monorepo root. This preserves the requested Gradle 7.6.4 distribution,
AGP 7.2.2 / Kotlin 1.8.0 and the existing application ID. The retained wrapper
bootstrap JAR matches the official Gradle 8.14.3 checksum; this is distinct from
the distribution selected in wrapper properties. It does not solve signature conflicts with an already installed reader. Use
a dedicated test phone with USB debugging authorization and a local escape route.

## Phone-first trial and stopping

Enable FocalFlow on the phone before starting the bounded launcher. It waits
locally with filtering inactive until a matching SESSION_READY arrives. Leave
settings for the task app, then navigate yourself. Ctrl+C stops the launcher;
Terminal closure, SIGHUP or launcher/runner death also trigger guardian cleanup.
The guardian's independent wall cap is 600 seconds. Phone-side acknowledged-session
EOF requests service shutdown; the selected baseline still has a capture race.

The TalkBack menu's pause AI action keeps standard browsing; resume starts a fresh
connection/capture. For a never-connected wait when USB is unavailable, open system
Accessibility settings and turn FocalFlow off locally. Check the phone service and
touch-exploration state rather than inferring success from desktop output.

Keep round logs private. They can include snapshots, screenshots, transcripts and
model messages. Runtime temporary cleanup is best effort; provider content
retention and historical artifacts are outside that cleanup.
