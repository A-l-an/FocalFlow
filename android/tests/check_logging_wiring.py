#!/usr/bin/env python3
"""Static wiring checks only. This does not compile TalkBack or prove Android runtime behavior."""
from pathlib import Path
import re

repo = Path(__file__).resolve().parents[1]
utils = repo / 'utils/src/main/java/com/google/android/accessibility/utils'
talkback = repo / 'talkback/src/main/java/com/google/android/accessibility/talkback'
checks = 0
failures = 0


def check(condition, description):
    global checks, failures
    checks += 1
    if not condition:
        failures += 1
    print(('PASS ' if condition else 'FAIL ') + description)


service = (talkback / 'TalkBackService.java').read_text()
check('NodeMappingTest.' not in service, 'service does not execute production debug tests')
check('setLogTypesEnabled(' not in service and 'enableLogType(' not in service,
      'service startup does not opt into sensitive persistence')
check('fileLogger.initializeTransport()' in service and 'fileLogger.closeTransport()' in service,
      'service owns transport lifecycle')
check('fileLogger.publishVirtualTree(captureContext, virtualTreeJson, interaction)' in service
      and 'fileLogger.isLogTypeEnabled("virtual_tree_logs")' not in service,
      'service publishes VAT independently of debug switch')

# Deliberately scoped: identify direct payload/exception logging in these touched call paths.
tracker = (utils / 'UserInteractionTracker.java').read_text()
text_change = tracker[tracker.index('public void recordTextChangeInteraction('):tracker.index('public void recordDoubleTapInteraction(AccessibilityNodeInfo')]
double_tap = tracker[tracker.index('public void recordDoubleTapInteraction(String'):tracker.index('public void saveInteractionsToFile()')]
check('getSafeString(beforeText)' not in text_change and 'getSafeString(afterText)' not in text_change,
      'unguarded text-change Logcat omits content')
check('" + elementInfo' not in double_tap, 'unguarded double-tap Logcat omits content')
# Other tracker node logs require ui_interaction_logs=true; LogUtils i/d/v remain behind
# the production default ERROR threshold. They are not default-payload failures.
scopes = [
    (utils / 'VirtualTreeBuilder.java', r'getMessage\(\)'),
    (utils / 'output/SpeechControllerImpl.java', r'\blogText\b|spansToStringForLogging|\+\s*(replacementText|item)\b|getMessage\(\)'),
]
for path, denied in scopes:
    calls = re.findall(r'(?:Log|LogUtils)\.[vdiwe]\([^;]*?\);', path.read_text(), re.S)
    # Ignore prose within string literals; inspect interpolated values/expressions.
    expressions = [re.sub(r'"(?:\\.|[^"\\])*"', '""', call) for call in calls]
    check(not any(re.search(denied, call) for call in expressions), path.name + ' direct sensitive log arguments removed')
pc = (utils / 'PcConnectionManager.java').read_text()
manager = (utils / 'VirtualTreeManager.java').read_text()
check('captureVirtualTree(captureContext, virtualTreeJson)' in service
      and service.index('captureVirtualTree(captureContext, virtualTreeJson)') < service.index('fileLogger.publishVirtualTree(captureContext, virtualTreeJson, interaction)'),
      'local capture accepted before operational publication')
check('fileLogger.logCapturedUiElements(captureContext, hierarchyJson)' in service
      and 'fileLogger.logJson("ui_elements_log"' not in service,
      'optional UI history carries capture ownership to the final guarded write boundary')
check(pc.count('applyFilteredVirtualTree(context, id, payload)') == 1 and 'future == null || !trees.ownsRequest(context, id)' in pc and 'savePcUpdatedVirtualTree' not in pc
      and 'updateVirtualTree(' not in pc and 'VirtualTreeValidator.parseMessage(message)' in pc,
      'only registered current responses use final validated application; legacy push removed')
check('private void savePcUpdatedVirtualTree' in manager and 'public synchronized void updateVirtualTree' not in manager,
      'unvalidated public setter and persistence bypass removed')
check('NodeMappingManager' not in pc and 'NodeMappingManager' not in manager,
      'remote application has no mapping-write dependency')
focus = (utils / 'FocusProxy.java').read_text()
check('e.getMessage()' not in focus and ', e);' not in focus,
      'invalid-node focus errors omit exception text and Throwable')
observation = service[service.index('  private void observeFocalFlowEvent('):service.index('  @Override', service.index('  private void observeFocalFlowEvent('))]
double_tap_capture = service[service.index('  public void logAfterDoubleTap()'):service.index('  public static int getServiceState()')]
check('invalidateForEvent(' not in observation and 'delayLogUiElements' not in observation
      and 'invalidateContext()' not in double_tap_capture
      and 'new NativeTreeSnapshot' not in service,
      'ordinary content/menu/double-tap events do not invalidate or collect equivalence evidence')
drain = service[service.index('  private void drainCaptures()'):service.index('  public void logAfterDoubleTap()')]
check('synchronized (VirtualTreeManager.getInstance())' in drain
      and drain.index('pendingOperation()') < drain.index('pc.beginCapture()') < drain.index('capture.accept(')
      and 'captureCompletion.whenComplete' in drain
      and 'trigger.sameTask(pc.currentContext())' in drain and 'pc.isConnected()' in drain,
      'idle check and token reservation share request lock; native capture executes after reservation')
check('event.getEventType() == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED' in service
      and 'event.getEventType() == AccessibilityEvent.TYPE_VIEW_SCROLLED' in service
      and 'uiLoggingDelayHandler.delayLogUiElementsAfterWindowChange()' in service
      and 'uiLoggingDelayHandler.delayLogUiElementsAfterScroll()' in service
      and 'uiLoggingDelayHandler.delayLogUiElementsAfterDoubleTap()' in double_tap_capture,
      'original window/scroll/double-tap capture callbacks remain wired')
check('pendingCaptureWork = captureWork' in service and 'loggingExecutor.execute(this::drainCaptures)' in service
      and 'if (pendingCaptureNode != null) pendingCaptureNode.recycle()' in service,
      'one coalesced pending capture releases replaced native handle copies')
check('synchronized (virtualTreeManager)' in focus and 'isFilteringActive()' in focus,
      'inactive capture uses native traversal before touching partial mapping')
check('requestCapturedUpdate(capture, interaction)' in (utils / 'FileLogger.java').read_text()
      and re.search(r'if\s*\(trailingIntent != intent\s*\|\|\s*trees\.isPaused\(\)\s*\|\|\s*!trees\.isCurrent\(context\)\)\s*return;', pc)
      and 'cancelTrailingCapture();' in pc,
      'capture publication uses bounded current trailing dispatch on shared scheduler')
check('CompletableFuture.failedFuture' not in pc and 'new ArrayBlockingQueue<Runnable>(32)' in pc
      and 'setRemoveOnCancelPolicy(true)' in pc, 'Java8 failure path, bounded writer, removable timeouts')
print(f'static_checks={checks} failures={failures}; device_validation=NOT_RUN')
raise SystemExit(bool(failures))
