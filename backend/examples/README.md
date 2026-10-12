# Synthetic offline flow

From the repository root, use the measured CPython 3.8.19 environment and
[SUPPORT.md](../SUPPORT.md)'s dependency scopes. The demo directly requires
transitions and ujson; the regression suite additionally needs requests, httpx
and openai (plus their dependencies). Replace the interpreter path:

```sh
FF_PYTHON=/absolute/path/to/python3.8
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 "$FF_PYTHON" -m unittest discover -v
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 "$FF_PYTHON" -m examples.offline_demo
```

The full measured suite executes 102 tests, including two installed sounddevice
0.5.1 source checks with native fakes. Without sounddevice those two skip; the
five-package minimum does not establish all 102 checks executed.

Verified locally with Python 3.8.19. No phone, ADB, credentials, model download,
audio device, or network access is needed. This is not a clean-install claim.
The demo blocks network/socket, subprocess, and service/audio SDK boundaries;
unexpected attempts abort the run. TTS/beep are recorded in memory, voice is a
fixed synthetic sentence, acquisition returns temporary copies of the fixtures,
and sending captures the actual serialized response. Temporary copies are
removed when the run finishes.

The CLI and `tests/test_offline_flow.py` use the same `run_demo()` and
`verify_outcome()` functions. The real `UIListener._process_message()` dispatches
`ROLE`/`INVALIDATE_CONTEXT` and versioned `REQUEST_UI_UPDATE` through admission, the serial execution path, acquisition,
`update_agent_state()`, and `receive_normal()`. Production planning, decision and
classification parsers, target selection, state transitions, VAT rewriting and
`UI_UPDATE` serialization all execute. None of those methods is replaced.
The tests also exercise a simple Talk mode B response on the same fixture.

All fixtures were created for this example, not captured from a device or study:

- `fixtures/synthetic_tree.json`: a fictional shelf; root node with a `children`
  mapping and six nodes in total. Element keys and synthetic UUID-shaped
  `virtualNodeId` values are intentionally different. Fields follow the current
  Android `VirtualTreeBuilder` schema; leaves omit `children`.
- `fixtures/synthetic.png`: a 2 × 2 white grayscale PNG, generated with Python's
  `struct`/`zlib`. It is only an image-encoding placeholder, not a rendered UI.
- `fixtures/fixed_responses.json`: hand-written planning, decision,
  classification and Talk responses with the production delimiters and JSON
  fields. **Fixed model responses, no inference.** These data demonstrate neither
  model accuracy nor reproduction of paper results. Existing production prompts,
  model names and selection strategies are unchanged.

The final summary includes:

```text
Synthetic fixture / fixed model responses (no inference).
requestId=synthetic-request-04; targets=element-open,element-title; state=waiting; external_calls=0
```

Assertions inspect actual nodes, preserved virtual IDs, the response request ID,
raw capture immutability, metadata containers and final waiting state. The former
root `bounds`/`children` pollution is now a production regression test.
Corrupting the action reference or a fixture virtual ID is rejected by the real
request path: an explicit error response contains no tree payload, and no partial
subtask, classification or focused candidate remains.

`tests/test_output_validation.py` exercises malformed/duplicate JSON, wrong
schemas/types, unknown or other-snapshot references, empty selections, Talk
category errors, and resource limits through the same production entry. The
initial limits are 64 KiB UTF-8 per model response, 8 MiB per full tree, 10,000
actual nodes, and depth 128 (root = 1). These are safety bounds, not performance
claims. Element aliases are keys in `children`, separate from canonical UUID
`virtualNodeId` values. Classification references stay within the decision's
selected subtrees. Cross-category overlap and action/context union remain valid.
Only actual-node `isVirtualFocusNode` booleans change in the full returned tree.

Empty model selections produce an explicit error even for a root-only capture;
this backend does not infer a legitimately empty screen from `isFocusable` or
from a failed filter. Android can separately accept an unchanged source with no
original focus. No phone, Android acceptance, TalkBack traversal, model accuracy,
clickability, cancellation, or cross-request timing guarantee is established by
this example. Talk mode A remains the existing no-action placeholder and returns an explicit correlated NO_OP acknowledgement. Epoch and
transport correlation use the v1 contract in `docs/protocol-v1.md`. `tests/test_freshness.py` separately runs real socketpair reader/worker and guarded audio boundaries with deterministic synthetic providers. This CLI alone is not that timing evidence.

The current snapshot is emitted as `{protocolVersion, context, tree}`; its raw tree fixture is unchanged. `fixtures/protocol_vectors.json` is shared byte-for-byte with the Android repository and includes invalid type/range cases. The optional `tests.protocol_bridge` CLI is invoked by Android tests with explicit file paths; normal backend tests require no other checkout.
