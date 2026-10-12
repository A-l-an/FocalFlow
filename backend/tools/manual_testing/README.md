# FocalFlow manual testing launcher

Run from this repository through `scripts/run-manual.sh`; no deployment to an
author-specific directory is needed. The three sibling entry files remain together,
and `manual_test.py` checks its sibling runtime SHA-256. The launcher is macOS/Darwin
only. Setup and operator paths are in [setup](../../../docs/setup.md).

Enable **FocalFlow on the phone first**, then start the computer launcher. The
phone can wait with AI filtering inactive, including when USB forwarding accepts
TCP before a desktop listener exists. The launcher distinguishes listening,
receiving ROLE, and successfully sending SESSION_READY. The readiness control
event does not count as a business failure/success or a chat/TTS call. Confirmation
sent is host-side evidence; phone application and actual task success remain
unobserved until separately checked. It uses the operator-selected private configuration,
BURGER_PRESET and original 24 chat / 12 TTS / 600 second runner limits. No endpoint,
prompt or task selection was changed. The selected chat model is read from the
explicit approved private configuration, validated as an identifier and forwarded
unchanged. The selected official chat configuration uses
`FOCALFLOW_CHAT_API_URL=https://api.openai.com/v1/chat/completions` and
`FOCALFLOW_CHAT_MODEL=gpt-6-luna`. Credentials stay only in the operator's private configuration. For exactly `gpt-6-luna`, requests
use `max_completion_tokens=2048` and `reasoning_effort=none`, without the legacy
`temperature` or `seed` fields. Other models retain the original request fields.
Text and image content are forwarded unchanged. See the
[official model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
for the supported interface; offline checks do not establish live model availability.

Before importing the live backend, a subprocess sends an unauthenticated streamed
GET to the configured chat endpoint using the same environment proxy, NO_PROXY
and CA settings as production. A fresh session disables implicit netrc credentials.
The entire probe has a six-second process timeout and does not read response
content or make a model call. A failure stops startup and attempts to turn off the
phone service. Any HTTP response (including 401/405) establishes transport
reachability only, not API credentials, quota, model availability or inference.
The production network error path also preserves allowlisted cause categories
from exception types and errno, never their URL/header/body/text.

The launcher holds a write end of an EOF pipe to an independent guardian. Closing
Terminal, SIGINT, SIGTERM, SIGHUP or killing the launcher closes that pipe. The
guardian independently enforces the 600 second wall budget from its own start,
including backend import/constructor startup. It observes leader exit with Darwin
`waitid(WNOWAIT)` without reaping the owned leader. Both an already exited leader
and a cooperative STOP therefore retain the PID/PGID ownership anchor until
TERM/KILL cleanup of the whole owned group completes; unrelated groups are not
signaled. A stop failure still attempts phone, reverse and safe-report cleanup;
`runner_cleanup=UNVERIFIED` and a nonzero exit report that failure without raw
exception contents. The console does not claim the runner stopped from phone
cleanup alone. The guardian then reaps the leader and removes
only the modern FocalFlow and legacy own accessibility components from the
current enabled list. Other services stay listed. Runner death and failure before
ROLE use the same cleanup. ADB cleanup reports `DISABLED` only after reading back
a list without the own components; USB failure reports `UNVERIFIED`. A disconnected
phone that was previously connected also disables itself through the Android
service main queue. If the phone never connected and USB is unavailable, open
system Accessibility settings on the phone and turn off FocalFlow locally.

Terminal output uses UTC time, stage, allowlisted code/cause and the private event
number. Each logical call failure and its matching error reply print once. The
private event file, guardian cleanup report and manual summary remain in the
operator-private log directory. Payload evidence remains private and is not
printed. Model response delivery does not prove phone application or task success.

Offline checks:

```sh
python -B tools/manual_testing/manual_test.py --check
python -B -m unittest tests.test_launcher_lifecycle -v
```

The selftest uses a fake module. Lifecycle tests use OS subprocesses, synthetic
settings and a fake ADB executable; network probes substitute only the HTTP
boundary. They neither connect to a phone nor read actual credentials or invoke
providers/audio. APK/service behavior, USB cleanup on the actual device, Terminal
closure and the complete manual task still require separate device acceptance.

The selected baseline retains [known issues](../../../docs/known-issues.md); complete
ordering and paper-result reproduction are not established.
