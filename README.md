# FocalFlow

FocalFlow helps blind and low-vision users explore mobile interfaces one task at a time. An Android app built on TalkBack captures the current screen; a Python backend selects relevant information and returns a smaller set of focus targets. Users navigate and activate controls themselves, and can ask for more information by voice.

[中文说明](README.zh-CN.md)

## 1. Project structure

```text
FocalFlow/
├── android/                  TalkBack-based Android app
│   ├── talkback/             Accessibility service, gestures and menus
│   ├── utils/                UI trees, node mapping, focus filtering and PC connection
│   └── braille/              Upstream TalkBack braille support
├── backend/
│   ├── run.py                Task planning, classification and voice-dialogue flow
│   ├── MobileAgent/          Prompts, task presets, model/speech APIs and validation
│   ├── tools/manual_testing/ Shared launcher for normal and test modes
│   ├── examples/             Offline example with a synthetic interface
│   └── tests/                Automated tests
├── scripts/                  Commands for launching and checking the demo
└── docs/                     Architecture, setup details and communication protocol
```

The phone and computer communicate through **USB/ADB and a local TCP connection**. AI-generated speech and voice recognition run on the computer; ordinary TalkBack speech runs on the phone.

## 2. Components you can reuse

| What you want to build | Start here |
| --- | --- |
| Convert Android accessibility nodes to a JSON tree and map them back to native controls | [VirtualTreeBuilder.java][tree-builder] and [NodeMappingManager.java][node-mapping] |
| Restrict screen-reader focus to selected interface regions | [FocusProxy.java][focus-proxy] and [VirtualTreeManager.java][tree-manager] |
| Return results to Android without applying an outdated screen's analysis | [PcConnectionManager.java][pc-connection], [protocol.py](backend/MobileAgent/protocol.py) and [validation.py](backend/MobileAgent/validation.py) |
| Adapt task planning and UI classification to another task | [MobileAgentStateMachine](backend/run.py), [task_presets.py](backend/MobileAgent/task_presets.py) and [prompt.py](backend/MobileAgent/prompt.py) |
| Add another information category to the existing focus set after a voice request | The Talk stage in [run.py](backend/run.py) and speech functions in [api.py](backend/MobileAgent/api.py) |

The Android components are integrated with TalkBack and should be reused with their tree and node-mapping dependencies. Results keep the full UI tree and change the `isVirtualFocusNode` flags; see the [protocol](docs/protocol-v1.md) when replacing the backend.

## 3. Run and use the demo

The launcher targets **macOS**, with **Python 3.8.19** as the reference environment. You also need an Android test phone with USB debugging and multi-finger accessibility gestures, Android platform-tools (`adb`), and FFmpeg on your `PATH`.

### Step 1: Prepare the Python backend

Run these commands in the same terminal:

```sh
git clone https://github.com/A-l-an/FocalFlow.git
cd FocalFlow
python3.8 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-offline.txt
python -m pip install numpy==1.24.4 sounddevice==0.5.1 soundfile==0.13.1 scipy==1.10.0 torch==2.4.1 openai-whisper==20240930
export FOCALFLOW_PYTHON="$(pwd)/.venv/bin/python"
python -c 'import whisper; whisper.load_model("base")'
```

The last command downloads the local speech-recognition model ahead of the first voice interaction. On macOS, `brew install ffmpeg` installs FFmpeg if needed. Allow microphone access for the terminal when prompted.

### Step 2: Build and install the Android app

Prepare **JDK 16**, **Android SDK 34** and **NDK 25.2.9519653**. Set the SDK location in `android/local.properties` (`sdk.dir=/path/to/Android/sdk`). Connect the phone by USB, accept its debugging prompt, then run:

```sh
adb devices
export JAVA_HOME="$(/usr/libexec/java_home -v 16)"
cd android
./gradlew --no-daemon --console=plain :assemblePhoneDebug
cd ..
adb install -r android/build/outputs/apk/phone/debug/*.apk
```

Use a test phone: package ID `com.android.talkback` can conflict with an existing app signed with a different key. More build details are in [setup](docs/setup.md#android-build).

### Step 3: Configure model access

```sh
mkdir -p "$HOME/.config/focalflow"
cp -n backend/tools/manual_testing/providers.env.example "$HOME/.config/focalflow/providers.env"
chmod 600 "$HOME/.config/focalflow/providers.env"
export FOCALFLOW_CONFIG="$HOME/.config/focalflow/providers.env"
```

Edit that file and replace `FOCALFLOW_CHAT_API_TOKEN` and `OPENAI_API_KEY` with your own keys. The example uses `gpt-6-luna` for screen analysis and `gpt-4o-mini-tts` for speech. The chat model must support text and image input.

Screen images, interface text and dialogue text are sent to the configured chat/TTS services, which may charge for API use. Keep the config and runtime logs private.

### Step 4: Start the demo

1. Keep **one phone** connected by USB. In the phone's system accessibility settings, enable **FocalFlow**.
2. From the repository root, start the computer backend:

   ```sh
   ./scripts/run.sh
   ```

3. After the terminal reports that the backend session is ready, open Meituan Takeout on the phone. The default task is **“order a hamburger for delivery”**. Wait for the page description and analysis before exploring the filtered controls.

The launcher sets up ADB forwarding. Normal mode keeps running until you stop it. Press **Ctrl+C** to stop, then confirm FocalFlow is off in the phone's accessibility settings. For a ten-minute test session, use `./scripts/run-manual.sh` instead.

### Step 5: Explore and request more information

| Phone gesture | Action |
| --- | --- |
| One-finger swipe left/right | Move between accessible focus targets |
| One-finger double-tap | Activate the focused control |
| Two-finger swipe up/down | Scroll the page; page changes can trigger another analysis |
| **Two-finger triple-tap and hold** (hold the third tap) | Request more information about the current page |

For voice interaction, wait until the page analysis is complete, then perform the last gesture. The **computer** reads the available information categories. After the recording cue, speak into the **computer microphone**—for example, ask in Chinese, “再看看价格” (“show prices too”). Recording ends automatically after **five seconds**. The Talk stage can add the requested category's nodes while retaining the existing focus set; repeat to request another category.

The TalkBack menu also provides **Use standard browsing (pause AI)** and **Enable AI filtering**. If nothing responds, first check that FocalFlow is actually enabled on the phone and inspect the terminal error. A connected backend alone does not confirm that filtering is active.

This remains a research prototype: complete real-device task flows and multi-round voice disclosure are still awaiting verification.

**No phone yet?** After installing `requirements-offline.txt`, run `./scripts/offline-demo.sh` to inspect the flow using a synthetic screen and fixed responses. It makes no API calls. `./scripts/check-offline.sh` runs the automated checks.

---

[Architecture](docs/architecture.md) · [Detailed setup](docs/setup.md) · [Protocol](docs/protocol-v1.md)

FocalFlow code and documentation are licensed under [Apache-2.0](LICENSE). See [third-party licenses](LICENSES/README.md) for bundled components.

[tree-builder]: android/utils/src/main/java/com/google/android/accessibility/utils/VirtualTreeBuilder.java
[node-mapping]: android/utils/src/main/java/com/google/android/accessibility/utils/NodeMappingManager.java
[focus-proxy]: android/utils/src/main/java/com/google/android/accessibility/utils/FocusProxy.java
[tree-manager]: android/utils/src/main/java/com/google/android/accessibility/utils/VirtualTreeManager.java
[pc-connection]: android/utils/src/main/java/com/google/android/accessibility/utils/PcConnectionManager.java
