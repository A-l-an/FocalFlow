# Known issues and evidence limits

The initial directory integration preserved these issues. Follow-up repairs and
remaining device-validation limits are recorded separately below.

| Issue | Evidence / current status |
| --- | --- |
| Merchant activation stalls | The last Luna real-page trial reached merchant-related navigation but did not complete the intended activation/ordering flow. Preserved as an observed device failure; its repair direction remains in private incident notes. No complete burger-order success is claimed. |
| Immediate desktop socket restart | Successive local listener runs can fail to bind while prior connections remain in TIME_WAIT. The selected paired baseline does not include the unfinished SO_REUSEADDR/PORT_IN_USE startup changes. Wait for the port to clear before another round; do not infer that an UNKNOWN startup code is a model failure. |
| Retiring capture after EOF | An admitted Android capture can still satisfy the old token after socket closure and restore source before queued disableSelf completes. The selected Android baseline retains this independently reproduced race. Clearing mappings prevents writes into a new service's map, but that is not a fix for capture-token revocation. |
| Setup and portability | A fresh Python venv on the reference macOS host passed installation and offline Python/static checks, with two optional sounddevice-source skips and Java tools explicitly skipped. Fresh-OS/live setup, other Python/JDK/platform combinations and Linux/Windows guardian/audio support remain unverified. |
| Model and UI semantics | Structural validation does not prove the selected region is useful/correct. App trees can be incomplete; screenshot and tree capture are not pixel-atomic. |

A successful synthetic test, APK build, readiness ACK, TCP send or filtered-tree
application establishes only that boundary. It does not establish complete human
navigation, model accuracy or paper-result reproduction. The last real Luna run
used a newer startup-only backend variant than the selected offline-paired source;
see [source baseline](source-baseline.md). No new phone/API/audio trial is performed
as part of this packaging migration.

Do not attach private incident logs, real screenshots, speech, API config or
credentials to public issues. Reproducible reports should use synthetic fixtures,
content-free error IDs, tool versions and the source revision.

## Native node identity repair (2026-10-13)

Reverse lookup now uses Android native-node identity through
`AccessibilityNodeInfoCompat.equals`/`hashCode`. Different native nodes with the
same layout attributes no longer overwrite each other's virtual-node mapping.
Owned node copies are removed from reverse lookup before recycling; string-based
description lookup returns no result when the description is ambiguous.

The synthetic regression fails before the repair (14 failures across 46 checks)
and passes after it. Existing Java regressions and Android signature/build checks
pass; an independent 508-check identity stress probe also passed. These checks
establish the mapping defect and its repair, not the cause of the earlier real
merchant-activation stall. Native device acceptance remains under investigation.
