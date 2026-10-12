# Measured support and offline setup

The supported reproduction path is the synthetic production-flow demo and the
offline unittest suite, measured on macOS arm64 with CPython 3.8.19. It uses the
actual `run.py` listener/state machine, parsers and tree rewriting. Fixed model
responses replace inference. Phone behavior, model accuracy, audio hardware,
live providers and fresh-OS installation are not verified by these checks. A fresh
venv installation and offline Python/static checks subsequently passed on the
reference host; see [verification](../docs/verification.md#fresh-python-virtual-environment).

Use an existing environment with the versions in
`requirements-offline.txt`. From the source root, replace the interpreter path:

```sh
FF_PYTHON=/absolute/path/to/python3.8
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 "$FF_PYTHON" -m unittest discover -v
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 "$FF_PYTHON" -m examples.offline_demo
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 "$FF_PYTHON" test.py
```

The demo reports `external_calls=0`, selected synthetic targets and
`state=waiting`. The last command is an inert manual-probe notice. Importing
`test.py` is also inert. Only `python test.py --live` opts into the real TTS
provider and audio output; it is not part of offline verification and requires
valid `OPENAI_API_KEY` configuration and the live audio dependencies below.

The demo blocks network, subprocess and service/audio imports. The suite also
tests real Requests/OpenAI/httpx behavior against synthetic adapters; provider
and audio operations are replaced. Some lifecycle checks use local sockets.
No phone, ADB, model weights, credentials or historical study files are needed.
See [examples/README.md](examples/README.md) for fixture provenance and limits.

## Dependency scopes

| Scope | Dependencies and measured versions | Support limit |
| --- | --- | --- |
| Demo and production module imports | transitions 0.9.2 (requires six; installed 1.16.0), ujson 5.10.0 | Actual synthetic flow tested |
| Offline regression suite (minimal dependencies) | Above plus requests 2.32.3, httpx 0.27.2, openai 1.52.2 and their normal dependencies | Real SDKs with synthetic transports; two optional sounddevice source checks skip if that package is absent |
| Live chat | requests 2.32.3 | Credentials and endpoint required; service behavior unverified |
| Live TTS, recording and speech recognition | openai 1.52.2, httpx 0.27.2, numpy 1.24.4, sounddevice 0.5.1, soundfile 0.13.1, scipy 1.10.0, torch 2.4.1, openai-whisper 20240930 | Metadata only for audio/ML packages except the two sounddevice source checks below; no native audio, device, model load or download run |
| Legacy perception / evaluation / analysis | CLIP, ModelScope, DashScope, Transformers, Pillow, OpenCV, Android evaluation data tooling, plotting packages | Outside the supported offline entry; not a reproduced environment |

The measured run executed all 145 tests, including two checks in
`tests/test_freshness.py` that read the installed sounddevice 0.5.1 source and
execute its `_StreamBase.close` method with mocked native operations. They do
not import the audio runtime or open a device. If sounddevice is absent, those
two checks are skipped; the five-package minimum does not by itself reproduce
all 145 executed checks. Sounddevice is optional for this source-level coverage,
not an added runtime requirement for the offline demo.

`requirements-offline.txt` deliberately lists the five direct imports needed by
the demo and minimal suite. It is not a transitive lock. The 165-entry
`requirements.txt` preserves the legacy research environment and its two Git
pins; it is not the recommended offline setup and may require platform-specific
packages or model/data downloads. Seven author-local file references were
replaced by installed package versions without upgrading packages. License and
weight-redistribution questions remain in [THIRD_PARTY.md](THIRD_PARTY.md).

The original reference run used existing packages. A later fresh venv installed
the five direct dependencies plus transitives and passed offline checks, with two
optional sounddevice-source checks skipped and no Java tools supplied. If an
approved local wheelhouse is available,
an offline installation can be attempted separately with:

```sh
python -m pip install --no-index --find-links /path/to/local/wheels -r requirements-offline.txt
```

That command is a setup option, not a verified result. Missing wheels should be
reported instead of falling back to a download. `ModuleNotFoundError` means the
chosen environment lacks a required package; it is not evidence the business
flow failed. CPython versions other than 3.8.19 have not been established here.

## Configuration and live boundary

`.env.example` contains deliberately invalid placeholders. The program does not
load `.env` automatically; live execution requires explicitly exported values.
The runtime rejects missing and placeholder credentials/URLs. The synthetic
commands above need none of them. `run.py` as a script is a live ADB/server entry,
so it is not an offline startup command. It uses `FOCALFLOW_ADB` or PATH lookup. The bounded manual entry and source-level
live handoff in [the root README](../README.md#try-the-phone-first-manual-flow-on-macos) are
outside this offline support scope.

Source-export tests do not establish Git-history safety, permission to publish
study material, or a dependency vulnerability assessment. Any repository-host
default-branch vulnerability notice is not scoped evidence about this candidate.
