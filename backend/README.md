# FocalFlow Python backend

The Python component contains the existing listener/state machine, provider/audio
boundaries, task presets and synthetic tests. Start at the [root README](../README.md)
for the integrated setup and evidence scope.

| Entry / module | Role |
| --- | --- |
| [run.py](run.py) | UIListener connection/admission/worker lifecycle and MobileAgentStateMachine stages; direct live script retains the hospital preset default |
| [MobileAgent/protocol.py](MobileAgent/protocol.py), [validation.py](MobileAgent/validation.py) | Versioned ownership and bounded parsing/tree/result validation |
| [MobileAgent/controller.py](MobileAgent/controller.py) | ADB tree/screenshot acquisition and retained legacy direct-control helpers |
| [MobileAgent/api.py](MobileAgent/api.py), [config.py](MobileAgent/config.py) | Chat, TTS, PC microphone/Whisper and explicit environment configuration |
| [MobileAgent/prompt.py](MobileAgent/prompt.py), [chat.py](MobileAgent/chat.py), [task_presets.py](MobileAgent/task_presets.py) | Preserved prompts, messages and fixed presets |
| [tools/manual_testing](tools/manual_testing/README.md) | Bounded macOS burger trial, guardian and private config |
| [examples](examples/README.md), [tests](tests) | Synthetic demo, offline regressions and Python/Java bridges |
| [evaluation](evaluation), [statisticAnalysis.py](statisticAnalysis.py) | Retained legacy scripts outside the supported entry |

From this directory with your prepared Python environment:

```sh
python3.8 -B -m examples.offline_demo
python3.8 -B -m unittest discover -v
python3.8 -B tools/manual_testing/manual_test.py --check
```

These offline commands use no provider, device, credentials or native audio.
Live `python run.py` requires explicitly exported API variables and ADB;
`.env.example` is not automatically loaded. ADB uses `FOCALFLOW_ADB` or PATH lookup.
The manual launcher uses a separate strict seven-field mode-600 private config.

See [SUPPORT](SUPPORT.md), [developer map](AGENT.MD),
[canonical protocol](../docs/protocol-v1.md), [known issues](../docs/known-issues.md)
and [licensing status](../docs/licensing-status.md). No complete ordering flow or
paper reproduction is established by these source checks.
