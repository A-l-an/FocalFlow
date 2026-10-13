#!/usr/bin/env python3
"""Compile selected production Java classes offline using an existing org.json jar/JDK.

Usage: python3 tests/run_sensitive_logging_tests.py --json-jar PATH [--java-home PATH]
Android stubs model file roots, Logcat, synthetic node handles and a fallback sentinel.
This is not a device test; real mapping/receiver/validator/manager classes are executed.
"""
import argparse
import pathlib
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--json-jar', required=True, type=pathlib.Path)
parser.add_argument('--java-home', type=pathlib.Path)
parser.add_argument('--android-jar', type=pathlib.Path)
parser.add_argument('--backend', type=pathlib.Path)
parser.add_argument('--python38', type=pathlib.Path)
parser.add_argument('--continuity-mode', choices=('delay', 'events', 'gestures', 'queue', 'admission', 'coalescing', 'reservation'))
parser.add_argument('--service-source', type=pathlib.Path)
parser.add_argument('--utils-source', type=pathlib.Path)
parser.add_argument('--mapping-identity-only', action='store_true')
parser.add_argument('--maintenance-mode', choices=('fields', 'optional'))
args = parser.parse_args()
repo = pathlib.Path(__file__).resolve().parents[1]
java = str(args.java_home / 'bin/java') if args.java_home else 'java'
javac = str(args.java_home / 'bin/javac') if args.java_home else 'javac'
source = args.utils_source or repo / 'utils/src/main/java/com/google/android/accessibility/utils'
names = ['ConnectionLimits.java', 'SnapshotContext.java', 'FileLogger.java', 'PcConnectionManager.java', 'VirtualTreeManager.java', 'NodeMappingManager.java', 'FocusProxy.java', 'DelayHandler.java', 'VirtualTreeBuilder.java']
if (source / 'NodeProperties.java').exists():
    names.append('NodeProperties.java')
if (source / 'NativeTreeSnapshot.java').exists():
    names.append('NativeTreeSnapshot.java')
if (source / 'VirtualTreeValidator.java').exists():
    names.append('VirtualTreeValidator.java')
if (source / 'TransportArtifactStore.java').exists():
    names.append('TransportArtifactStore.java')
with tempfile.TemporaryDirectory(prefix='focalflow-logging-test-') as tmp:
    classes = pathlib.Path(tmp) / 'classes'
    classes.mkdir()
    menu_action = repo / 'talkback/src/main/java/com/google/android/accessibility/talkback/contextmenu/FocalFlowMenuActions.java'
    if args.android_jar:
        stubs = repo / 'tests/offline_java/stubs'
        production = [p for p in sorted(stubs.rglob('*.java')) if p.relative_to(stubs).parts[0] != 'android'] + [source / name for name in names] + [menu_action]
        subprocess.run([javac, '--release', '8', '-encoding', 'UTF-8', '-cp', str(args.android_jar), '-d', str(classes)] + [str(path) for path in production], check=True)
        print('production_java8_android_signatures=PASS')
    inputs = sorted((repo / 'tests/offline_java').rglob('*.java'))
    inputs.extend(source / name for name in names)
    inputs.append(menu_action)
    # Compile the exact production raw serializer body; unrelated accessibility utilities
    # stay platform boundaries, just as the Service callback extraction below.
    raw_source = (source / 'AccessibilityNodeInfoUtils.java').read_text()
    raw_method = re.search(r'  public static JSONObject accessibilityNodeInfoToJson\(AccessibilityNodeInfo node\) \{.*?\n  \}', raw_source, re.S)
    if raw_method is None:
        raise RuntimeError('Production raw node serializer was not found')
    raw_harness = pathlib.Path(tmp) / 'RawNodeJsonHarness.java'
    raw_harness.write_text('''package com.google.android.accessibility.utils;
import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONObject;
import org.json.JSONException;
import com.google.android.libraries.accessibility.utils.log.LogUtils;
public final class RawNodeJsonHarness {
  private static final String TAG="SyntheticRawTree";
  private static String generateUniqueElementId() {return AccessibilityNodeInfoUtils.generateUniqueElementId();}
''' + raw_method.group() + '\n}\n')
    inputs.append(raw_harness)
    # Use the actual fallback property hash so identity regressions exercise real collisions.
    hash_method = re.search(r'  public static String generateElementHashId\(AccessibilityNodeInfo node\) \{.*?\n  \}', raw_source, re.S)
    if hash_method is None:
        raise RuntimeError('Production fallback property hash was not found')
    helper_stub = repo / 'tests/offline_java/stubs/com/google/android/accessibility/utils/AccessibilityNodeInfoUtils.java'
    helper_harness = pathlib.Path(tmp) / 'AccessibilityNodeInfoUtils.java'
    helper_harness.write_text(helper_stub.read_text().replace(
        'import android.view.accessibility.AccessibilityNodeInfo;',
        'import android.view.accessibility.AccessibilityNodeInfo;\nimport android.graphics.Rect;').replace(
        '  public static String generateElementHashId(AccessibilityNodeInfo node) { return "synthetic"; }',
        hash_method.group()))
    inputs.remove(helper_stub)
    inputs.append(helper_harness)
    # Execute the actual posted callback body, without compiling the full Android service.
    # Context, speech queue, and native capture remain explicit platform boundaries.
    service = (args.service_source or repo / 'talkback/src/main/java/com/google/android/accessibility/talkback/TalkBackService.java').read_text()
    callback = re.search(r'  private final Runnable recoveryAnnouncement = \(\) -> \{.*?\n  \};', service, re.S)
    if callback is None:
        raise RuntimeError('Production recovery callback was not found')
    callback_source = pathlib.Path(tmp) / 'RecoveryCallbackHarness.java'
    callback_source.write_text('''package com.google.android.accessibility.utils;
import android.content.Context;
import com.google.android.accessibility.talkback.Pipeline;
import com.google.android.accessibility.talkback.contextmenu.FocalFlowMenuActions;
public final class RecoveryCallbackHarness extends Context {
  public volatile PcConnectionManager.RecoveryNotice pendingRecoveryNotice;
  public int speechCalls, captureCalls;
  public final PipelineBoundary pipeline = new PipelineBoundary();
  public RecoveryCallbackHarness() { super(new java.io.File(".")); }
  public final class PipelineBoundary {
    public Pipeline.FeedbackReturner getFeedbackReturner() {
      return (event, part) -> { speechCalls++; return true; };
    }
  }
  private void logUIElementsToFile(String event, Object node) { captureCalls++; }
''' + callback.group().replace('private final Runnable', 'public final Runnable', 1) + '\n}\n')
    inputs.append(callback_source)
    capture = re.search(r'    (?:Runnable|java\.util\.function\.BiConsumer<SnapshotContext, AccessibilityNodeInfoCompat>) captureWork = .*? -> \{.*?\n    \};', service, re.S)
    if capture is None:
        raise RuntimeError('Production capture worker was not found')
    capture_source = pathlib.Path(tmp) / 'CaptureWorkHarness.java'
    observation = re.search(r'  private void observeFocalFlowEvent\(AccessibilityEvent event\) \{(.*?)\n  \}', service, re.S)
    if observation is not None:
        observation_body = observation.group(1)
    else:
        observation = re.search(r'    // Invalidate on every observed.*?\n    // 处理UI元素和虚拟树日志记录', service, re.S)
        if observation is None: raise RuntimeError('Production event observation was not found')
        observation_body = 'int eventType = event.getEventType();\n' + observation.group()
    observe_method = '''
  public int scheduledCaptures;
  private final DelayHandler<Object> uiLoggingDelayHandler = new DelayHandler<Object>() {
    public void handle(Object value) {}
    @Override public void delayLogUiElementsAfterWindowChange() { scheduledCaptures++; }
  };
  public void observe(AccessibilityEvent event) {
''' + observation_body + '\n  }\n'
    capture_source.write_text('''package com.google.android.accessibility.utils;
import android.content.Context;
import android.util.Log;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityEvent;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import com.google.android.accessibility.talkback.contextmenu.FocalFlowMenuActions;
import org.json.JSONObject;
public final class CaptureWorkHarness extends Context {
  private static final String TAG = "SyntheticCapture";
  private final FileLogger fileLogger;
  public NodeMappingManager focalFlowMappingManager;
  private final MenuBoundary menuManager = new MenuBoundary();
  private static final class MenuBoundary { boolean isMenuExist() { return false; } }
  public CaptureWorkHarness(FileLogger logger) { super(new java.io.File(".")); fileLogger=logger; }
  public AccessibilityNodeInfo root = new AccessibilityNodeInfo();
  private AccessibilityNodeInfo getRootInActiveWindow() { return AccessibilityNodeInfo.obtain(root); }
  private String getPackageName() { return "synthetic.talkback"; }
  private java.util.concurrent.CompletableFuture<JSONObject> captureCompletion;
  public Runnable capture(SnapshotContext triggerContext) {
    final NodeMappingManager captureMappingOwner = focalFlowMappingManager;
    AccessibilityNodeInfoCompat interactionNodeCopy = null;
    String triggerReason = "resume";
''' + capture.group() + '\n    return captureWork;\n  }\n' + observe_method + '}\n')
    if 'BiConsumer' in capture.group():
        capture_source.write_text(capture_source.read_text().replace('    AccessibilityNodeInfoCompat interactionNodeCopy = null;\n', '').replace('return captureWork;', 'return () -> captureWork.accept(triggerContext, null);'))
    elif 'final SnapshotContext captureContext =' not in capture.group():
        capture_source.write_text(capture_source.read_text().replace('capture(SnapshotContext triggerContext)', 'capture(SnapshotContext captureContext)'))
    inputs.append(capture_source)
    # Queue harness executes the complete production admission and drain, including
    # the future that owns the transport slot through response application.
    queue_methods = []
    for method in ('logUIElementsToFile', 'enqueueCaptureDrain', 'drainCaptures'):
        match = re.search(r'  private void ' + method + r'\(.*?\n  \}', service, re.S)
        if match is None and method == 'enqueueCaptureDrain': continue  # historical source negative control
        if match is None: raise RuntimeError('Production capture method missing: ' + method)
        queue_methods.append(match.group())
    queue_fields = service[service.index('  private final Object captureQueueLock'):service.index('  private final Handler recoveryHandler')]
    queue_source = pathlib.Path(tmp) / 'CaptureQueueHarness.java'
    queue_source.write_text("""package com.google.android.accessibility.utils;
import android.content.Context;
import android.util.Log;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import org.checkerframework.checker.nullness.qual.Nullable;
import com.google.android.accessibility.talkback.contextmenu.FocalFlowMenuActions;
import org.json.JSONObject;
import java.util.concurrent.*;
public final class CaptureQueueHarness extends Context {
  private static final String TAG="SyntheticQueue";
  private final FileLogger fileLogger;
  public NodeMappingManager focalFlowMappingManager;
  private final ExecutorService loggingExecutor;
  private final MenuBoundary menuManager=new MenuBoundary();
  private static final class MenuBoundary { boolean isMenuExist(){return false;} }
  public int builds;
  public AccessibilityNodeInfo root=new AccessibilityNodeInfo();
  public CaptureQueueHarness(FileLogger logger, ExecutorService executor) {super(new java.io.File("."));fileLogger=logger;loggingExecutor=executor;}
  private String getPackageName(){return "synthetic.talkback";}
  private AccessibilityNodeInfo getRootInActiveWindow(){builds++;return AccessibilityNodeInfo.obtain(root);}
  public void submit(String reason){logUIElementsToFile(reason,null);}
""" + queue_fields + '\n'.join(queue_methods) + '\n}\n')
    inputs.append(queue_source)
    ui_delay = re.search(r'  private class UiLoggingDelayHandler extends DelayHandler<Object> \{.*?\n  \}', service, re.S)
    mark_tap = re.search(r'  private void markDoubleTapTriggered\(\) \{.*?\n  \}', service, re.S)
    if ui_delay is None or mark_tap is None:
        raise RuntimeError('Production double-tap callbacks were not found')
    gesture_source = pathlib.Path(tmp) / 'UiDelayHarness.java'
    gesture_source.write_text('''package com.google.android.accessibility.utils;
import android.os.SystemClock;
import android.util.Log;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
public final class UiDelayHarness {
  private static final String TAG="SyntheticGesture";
  private static final long DOUBLE_TAP_PRIORITY_WINDOW_MS=5000;
  private long lastDoubleTapTime;
  public boolean doubleTapTriggered;
  private AccessibilityNodeInfoCompat lastDoubleTapNode;
  public final DelayHandler<Object> uiLoggingDelayHandler = new UiLoggingDelayHandler();
  public final java.util.List<String> captures = new java.util.ArrayList<>();
  private void logUIElementsToFile(String reason, AccessibilityNodeInfoCompat node) {
    captures.add(node==null?"null":node.getText().toString());
  }
  public void schedule(AccessibilityNodeInfoCompat node) {
    lastDoubleTapNode=node; markDoubleTapTriggered(); uiLoggingDelayHandler.delayLogUiElementsAfterDoubleTap();
  }
  public void renewPriority() {markDoubleTapTriggered();}
''' + ui_delay.group() + '\n' + mark_tap.group() + '\n}\n')
    inputs.append(gesture_source)
    subprocess.run([javac, '-encoding', 'UTF-8', '-cp', str(args.json_jar), '-d', str(classes)] +
                   [str(path) for path in inputs], check=True)
    if args.mapping_identity_only:
        raise SystemExit(subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
            'com.google.android.accessibility.utils.NodeMappingIdentityTest', str(pathlib.Path(tmp) / 'identity')]).returncode)
    if args.maintenance_mode:
        test = 'NodeFieldContractTest' if args.maintenance_mode == 'fields' else 'OptionalCaptureLogTest'
        raise SystemExit(subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
            'com.google.android.accessibility.utils.' + test]).returncode)
    if args.continuity_mode == 'reservation':
        raise SystemExit(subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
            'com.google.android.accessibility.utils.ReservationTriggerTest']).returncode)
    if args.continuity_mode == 'coalescing':
        raise SystemExit(subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
            'com.google.android.accessibility.utils.InteractionCoalescingTest']).returncode)
    if args.continuity_mode == 'admission':
        raise SystemExit(subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
            'com.google.android.accessibility.utils.CaptureAdmissionTest']).returncode)
    if args.continuity_mode == 'queue':
        raise SystemExit(subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
            'com.google.android.accessibility.utils.CaptureQueueTest']).returncode)
    if args.continuity_mode:
        raise SystemExit(subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
            'com.google.android.accessibility.utils.ContinuityTest', args.continuity_mode]).returncode)
    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'SensitiveLoggingTest', str(pathlib.Path(tmp) / 'data'), str(repo / 'tests/fixtures/synthetic_tree.json')], check=True)
    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'VatBoundaryTest', str(pathlib.Path(tmp) / 'vat'), str(repo / 'tests/fixtures/synthetic_tree.json')], check=True)

    freshness = [java, '-cp', str(classes) + ':' + str(args.json_jar), 'FreshnessTest', str(repo / 'tests/fixtures/synthetic_tree.json')]
    if args.backend and args.python38:
        freshness.extend([str(args.backend), str(args.python38)])
    subprocess.run(freshness, check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.CaptureDispatchTest', str(repo / 'tests/fixtures/synthetic_tree.json')], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.NodeMappingIdentityTest', str(pathlib.Path(tmp) / 'identity')], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.MappingRestartRaceTest', str(pathlib.Path(tmp) / 'mapping-restart')], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.ServiceExitTest', str(repo / 'tests/fixtures/synthetic_tree.json')], check=True)

    ready = [java, '-cp', str(classes) + ':' + str(args.json_jar),
             'com.google.android.accessibility.utils.SessionReadyTest', str(repo / 'tests/fixtures/synthetic_tree.json')]
    if args.backend and args.python38: ready.extend([str(args.backend), str(args.python38)])
    subprocess.run(ready, check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.TransportLifecycleTest', str(repo / 'tests/fixtures/synthetic_tree.json')], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'LocalRecoveryTest', str(repo / 'tests/fixtures/synthetic_tree.json')], check=True)

    recovery = [java, '-cp', str(classes) + ':' + str(args.json_jar),
                'com.google.android.accessibility.utils.RecoveryConnectionTest', str(repo / 'tests/fixtures/synthetic_tree.json')]
    if args.backend and args.python38:
        recovery.extend([str(args.backend), str(args.python38)])
    subprocess.run(recovery, check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.RecoveryLifecycleTest'], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.CapturePauseTest'], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.CaptureQueueTest'], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.CaptureAdmissionTest'], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.InteractionCoalescingTest'], check=True)

    subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar),
                    'com.google.android.accessibility.utils.ReservationTriggerTest'], check=True)

    continuity_failures = 0
    for mode in ('delay', 'events', 'gestures'):
        continuity_failures += subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar), 'com.google.android.accessibility.utils.ContinuityTest', mode]).returncode != 0
    if continuity_failures:
        raise RuntimeError('%d continuity regressions failed' % continuity_failures)

    for test in ('NodeFieldContractTest', 'OptionalCaptureLogTest'):
        subprocess.run([java, '-cp', str(classes) + ':' + str(args.json_jar), 'com.google.android.accessibility.utils.' + test], check=True)
