# FocalFlow developer guide

This is the maintained guide to the Python filtering path. It replaces legacy
scene examples, unversioned messages and speculative dataset-replay instructions.
Start with [README.md](README.md) and [SUPPORT.md](SUPPORT.md); use only the
self-created [synthetic examples](examples/README.md) for the supported offline
checks. No research records, phone logs or provider credentials are needed.

## Current flow

1. Android captures a complete tree and publishes a versioned snapshot. The
   backend receives ROLE, INVALIDATE_CONTEXT and UI/Talk requests through
   `run.py:UIListener`. The reader invalidates ownership independently of the
   serial business worker.
2. `MobileAgent/controller.py:get_screenshot_and_ui_elements` pulls the exact
   transport slot, validates context, acquires the screenshot, then pulls and
   validates the tree again. Offline acquisition substitutes temporary fixture
   copies at this boundary.
3. `update_agent_state` preserves the captured full tree and supplies derived
   UI information to `MobileAgentStateMachine`. The subtask, decision and
   classification stages use `MobileAgent/chat.py` and `prompt.py`.
4. `MobileAgent/validation.py` checks response size, schema and node references
   before building a candidate. Only actual-node `isVirtualFocusNode` booleans
   change; IDs, hierarchy, attributes and raw capture remain intact.
5. A correlated UI_UPDATE returns the complete candidate. Android independently
   validates it against the current source and pending request before enabling
   `FocusProxy` filtering. Desktop tests do not prove native traversal behavior.
6. REQUEST_TALK requires the successful decision's `baseRequestId` in the current
   context. Mode B can reveal classified context. Mode A returns `NO_OP`; it does
   not execute a phone action. Invalid/busy/stale requests cannot silently apply
   unsolicited tree updates.

## Canonical contracts and examples

| Concern | Source of truth |
| --- | --- |
| Framing, IDs, controls, error headers, current transport path | [docs/protocol-v1.md](docs/protocol-v1.md), implemented by `MobileAgent/protocol.py` |
| Full capture, synthetic IDs and node layout | [examples/fixtures/synthetic_tree.json](examples/fixtures/synthetic_tree.json) |
| Fixed planning/decision/classification/Talk responses | [examples/fixtures/fixed_responses.json](examples/fixtures/fixed_responses.json) |
| Cross-language invalid type/range cases | [examples/fixtures/protocol_vectors.json](examples/fixtures/protocol_vectors.json) |
| Executable production-flow example | [examples/offline_demo.py](examples/offline_demo.py), `tests/test_offline_flow.py` |
| Java-to-Python admission bridge | [tests/protocol_bridge.py](tests/protocol_bridge.py); called by the companion Android runner |

The tree fixture is not a wire message. Snapshots wrap it as
`{protocolVersion, context, tree}`; responses use the shared protocol's header and
`payload`. Element keys and UUID-shaped `virtualNodeId` values are different
identifiers. Reuse the executable fixture builder rather than copying obsolete
unversioned JSON. A missing context, stale request or malformed candidate is not
a compatibility fallback.

## Task preset data

`MobileAgent/task_presets.py` holds the existing hospital and burger presets as
frozen `TaskPreset` values. Pass a complete preset when constructing an agent:

```python
from MobileAgent.task_presets import BURGER_PRESET, TaskPreset
from run import MobileAgentStateMachine

agent = MobileAgentStateMachine(task_preset=BURGER_PRESET)
# Programmatic example only: all four values describe the same task.
custom = TaskPreset(
    instruction="Synthetic task goal",
    planning_hint="Synthetic planning context",
    decision_hint="Synthetic selection context",
    classification_hint="Synthetic grouping context",
)
custom_agent = MobileAgentStateMachine(task_preset=custom)
```

This changes task data within the existing fixed flow; no stage edits are needed.
The legacy `run.py:flag_burger` selects the default once at construction (0:
hospital, 1: burger). Later flag changes do not alter existing instances. Prefer
constructor injection to changing only `agent.instruction`. Keep full-prompt
parity and per-instance isolation tests in `tests/test_task_presets.py`; the
original prompt fixture provenance is in `tests/fixtures/task_preset_prompts.README.md`.
Prompt templates, model IDs, transitions and Talk modes remain separate contracts.

## Boundaries for changes

The existing injection points are the state machine's chat/TTS/voice/beep/model,
the listener's acquire/send operations, and failure-policy/clock arguments. The
offline demo replaces these external boundaries while preserving production
admission, parsing, selection, rewriting and serialization. Its fixed responses
prove neither inference nor paper-result reproduction.

Keep runtime files separate from optional debug history. Model calls, recording,
Whisper loading, ADB and native audio belong to the unverified live procedure in
README, not unit-test setup. `test.py` is inert by default; `--live` explicitly
opts into provider/audio work. Legacy perception helpers, evaluation and analysis scripts are outside this maintained entry and may have
different dependencies and data/logging behavior.

Freshness/cancellation, size limits, bounded retries and the 120-second eligibility
budget are engineering behavior changes from this audit. They cannot terminate
all opaque native/provider calls, retract a submitted speech buffer or guarantee
physical silence. Local pause/resume is implemented by the Android TalkBack menu;
see README for its device-validation limits. Never equate an offline pass with
phone acceptance, permission to publish, or the original study's result.

For attribution, contribution and publication gaps, retain the
[THIRD_PARTY.md](THIRD_PARTY.md) inventory and existing upstream notices. FocalFlow
paper metadata and the evaluation commit remain pending verification. Bug reports
should use synthetic fixtures, commit IDs and content-free errors.
