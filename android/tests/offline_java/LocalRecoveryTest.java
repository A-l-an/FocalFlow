import com.google.android.accessibility.utils.*;
import com.google.android.accessibility.talkback.*;
import com.google.android.accessibility.talkback.contextmenu.FocalFlowMenuActions;
import com.google.android.accessibility.utils.output.FeedbackItem;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import android.content.Context;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.JSONObject;

/** Real menu action/feedback adapter, receiver, manager and FocusProxy; platform boundaries are stubs. */
public final class LocalRecoveryTest {
  static final PcConnectionManager pc = ProtocolTestSupport.pc;
  static final VirtualTreeManager trees = ProtocolTestSupport.trees;
  static String fixture;
  static int checks, networkAttempts;
  static Context context;
  static final List<PcConnectionManager.RecoveryNotice> notices = new ArrayList<>();
  static final List<Feedback.Part.Builder> spoken = new ArrayList<>();
  static final Pipeline.FeedbackReturner pipeline = (event, part) -> { spoken.add(part); return true; };
  static void check(boolean value, String label) { checks++; if (!value) throw new AssertionError(label); }
  static JSONObject tree() { return new JSONObject(fixture); }
  static JSONObject title(JSONObject t) { return t.getJSONObject("children").getJSONObject("element-card").getJSONObject("children").getJSONObject("element-title"); }
  static JSONObject filtered() { JSONObject t = tree(); title(t).put("isVirtualFocusNode", false); return t; }
  static PcConnectionManager.RecoveryNotice lastNotice() { return notices.get(notices.size() - 1); }
  static JSONObject prepare() throws Exception {
    if (pc.isFilteringPaused()) pc.resumeFiltering();
    ProtocolTestSupport.connect(); pc.beginCapture();
    JSONObject source = tree();
    check(ProtocolTestSupport.capture(source), "valid local capture");
    check(!trees.isFilteringActive(), "pending capture uses native navigation until valid result");
    check(ProtocolTestSupport.apply(filtered()) && trees.isFilteringActive(), "current valid filtered result activates filtering");
    return source;
  }
  static JSONObject request() { pc.requestUiUpdate(null); return ProtocolTestSupport.last(); }
  static void error(JSONObject request) throws Exception {
    ProtocolTestSupport.raw(SnapshotContext.parse(request.getJSONObject("context")).message("UI_UPDATE", request.getString("requestId")).put("error", "HTTP_ERROR").toString());
  }
  static void expire(JSONObject request) throws Exception {
    Method method = PcConnectionManager.class.getDeclaredMethod("expire", SnapshotContext.class, String.class);
    method.setAccessible(true); method.invoke(pc, SnapshotContext.parse(request.getJSONObject("context")), request.getString("requestId"));
  }
  static void assertNative(FocusProxy proxy, AccessibilityNodeInfoCompat node, String label) {
    int before = AccessibilityNodeInfoUtils.fallbackCalls;
    check(proxy.shouldFocusNode(node) && AccessibilityNodeInfoUtils.fallbackCalls == before + 1, label);
  }
  public static void main(String[] args) throws Exception {
    fixture = Files.readString(Path.of(args[0])); Path temp = Files.createTempDirectory("focalflow-local-recovery-");
    context = new Context(temp.toFile()); pc.initialize(context); pc.setRecoveryFeedback(notices::add);
    System.setSecurityManager(new SecurityManager() {
      @Override public void checkPermission(java.security.Permission permission) { }
      @Override public void checkConnect(String host, int port) { networkAttempts++; throw new AssertionError("Local recovery must not open a connection"); }
    });
    NodeMappingManager mapping = new NodeMappingManager(context);
    AccessibilityNodeInfoCompat node = new AccessibilityNodeInfoCompat("synthetic-recovery-node");
    mapping.addMapping(title(tree()).getString("virtualNodeId"), node);
    FocusProxy.cleanup(); FocusProxy.initialize(mapping, trees); FocusProxy proxy = FocusProxy.getInstance();
    JSONObject originalSource = prepare(); check(!proxy.shouldFocusNode(node), "setup maps a node that current filtering excludes");
    String original = originalSource.toString(); JSONObject failedRequest = request(); error(failedRequest);
    check(!trees.isFilteringActive() && !pc.isFilteringPaused(), "current API error withdraws filter without persistent pause");
    check(!title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "fallback does not rewrite invalid result or source flags to true");
    assertNative(proxy, node, "mapped false node falls through original traversal after error");
    check(FocalFlowMenuActions.announce(context, pipeline, lastNotice()), "current failure enters existing local speech pipeline");
    check(spoken.get(spoken.size()-1).text.toString().equals(context.getString(R.string.focalflow_failure_restored)), "failure uses localized safe feedback resource");
    check((spoken.get(spoken.size()-1).options.flags & FeedbackItem.FLAG_NO_HISTORY) != 0, "local feedback retains existing no-history pattern");
    PcConnectionManager.RecoveryNotice oldNotice = lastNotice();
    prepare(); JSONObject currentRequest = request();
    ProtocolTestSupport.raw(ProtocolTestSupport.response(currentRequest, filtered()).toString());
    int speechCount = spoken.size(); String currentTree = trees.getVirtualTreeRoot().toString();
    error(failedRequest);
    check(trees.isFilteringActive() && currentTree.equals(trees.getVirtualTreeRoot().toString()), "stale error cannot clear newer valid filtering");
    check(!FocalFlowMenuActions.announce(context, pipeline, oldNotice) && spoken.size() == speechCount, "queued old failure is rejected again at actual speech adapter entry");
    for (JSONObject candidate : new JSONObject[] {tree().put("text", "changed"), new JSONObject(), allFalse(tree())}) {
      prepare(); CompletableFuture<JSONObject> future = pc.requestUiUpdate(null); JSONObject req = ProtocolTestSupport.last();
      ProtocolTestSupport.raw(ProtocolTestSupport.response(req, candidate).toString());
      check(future.isCompletedExceptionally() && !trees.isFilteringActive(), "current invalid/empty filtering withdraws without accepting candidate");
      assertNative(proxy, node, "invalid result uses original traversal");
    }
    prepare(); JSONObject timed = request(); expire(timed);
    check(!trees.isFilteringActive(), "timeout withdraws filtering"); assertNative(proxy, node, "timeout native path");
    prepare(); CompletableFuture<JSONObject> cancelled = pc.requestUiUpdate(null); cancelled.cancel(false);
    check(!trees.isFilteringActive(), "Future cancellation withdraws filtering");
    prepare(); JSONObject menuPending = request(); SnapshotContext beforeMenu = pc.currentContext();
    FocalFlowMenuActions.menuOpened();
    check(beforeMenu.equals(pc.currentContext()), "opening existing menu retains active request context");
    check(!FocalFlowMenuActions.isCaptureAllowed(true), "visible menu blocks capture");
    check(FocalFlowMenuActions.isCaptureCurrent(true, pc.currentContext()), "menu does not revoke already admitted capture");
    check(FocalFlowMenuActions.isCaptureCurrent(false, beforeMenu), "admitted capture remains current after menu settles");
    ProtocolTestSupport.raw(ProtocolTestSupport.response(menuPending, filtered()).toString());
    check(trees.isFilteringActive(), "result admitted before menu still applies to its captured source");
    check(FocalFlowMenuActions.isCaptureAllowed(false), "stable native focus permits future fresh capture");
    prepare();
    FileLogger publisher = new FileLogger(context); publisher.initializeTransport();
    publisher.enableLogType("virtual_tree_logs");
    publisher.publishVirtualTree(pc.currentContext(), tree(), null);
    Path slot = temp.resolve("screen_reader_logs/virtual_tree_logs/User_transport/Task_transport/virtual_tree_current.json");
    String beforePauseSlot = Files.readString(slot);
    long beforePauseFiles;
    try (java.util.stream.Stream<Path> files = Files.walk(temp)) { beforePauseFiles = files.filter(Files::isRegularFile).count(); }
    CompletableFuture<JSONObject> pending = pc.requestUiUpdate(null); JSONObject old = ProtocolTestSupport.last(); SnapshotContext oldCapture = pc.currentContext();
    check(FocalFlowMenuActions.titleResource() == R.string.focalflow_restore_browsing, "existing menu exposes local restore action");
    check(FocalFlowMenuActions.handle(R.id.focalflow_filtering), "actual local menu adapter handles restore");
    check(pc.isFilteringPaused() && !trees.isFilteringActive() && pending.isCompletedExceptionally(), "restore cancels pending and persists pause locally");
    check(FocalFlowMenuActions.titleResource() == R.string.focalflow_resume_ai, "paused menu offers explicit enable action");
    check(context.getSharedPreferences("focalflow_recovery", Context.MODE_PRIVATE).getBoolean("paused", false), "pause writes existing SharedPreferences API");
    int wireSize = ProtocolTestSupport.wire.toString().length();
    check(pc.beginCapture() == null && !trees.captureVirtualTree(oldCapture, tree()), "paused producer cannot capture or publish old token");
    pc.invalidateContext(); pc.requestCapturedUpdate(oldCapture, tree());
    publisher.publishVirtualTree(oldCapture, tree().put("text", "paused queued capture"), null);
    check(beforePauseSlot.equals(Files.readString(slot)), "paused queued publication cannot replace transport slot");
    try (java.util.stream.Stream<Path> files = Files.walk(temp)) {
      check(files.filter(Files::isRegularFile).count() == beforePauseFiles, "pause also prevents queued optional capture history writes");
    }
    check(pc.requestUiUpdate(null).isCompletedExceptionally() && pc.requestTalk().isCompletedExceptionally(), "paused request APIs fail locally");
    FocalFlowMenuActions.requestDetails(context, pipeline);
    check(ProtocolTestSupport.wire.toString().length() == wireSize, "no request or control frames are sent during persistent pause");
    ProtocolTestSupport.raw(ProtocolTestSupport.response(old, filtered()).toString()); error(old);
    check(!trees.isFilteringActive() && pc.isFilteringPaused(), "late result/error cannot re-enable paused filtering");
    assertNative(proxy, node, "explicit restore uses native mapping bypass");
    check(FocalFlowMenuActions.announce(context, pipeline, lastNotice()), "pause feedback remains current after connection cleanup");
    Field paused = VirtualTreeManager.class.getDeclaredField("paused"); paused.setAccessible(true); paused.set(trees, false);
    pc.initialize(new Context(temp.toFile()));
    check(pc.isFilteringPaused(), "initialization reloads stored pause instead of silently enabling capture");
    PcConnectionManager.RecoveryNotice pauseNotice = lastNotice();
    check(FocalFlowMenuActions.handle(R.id.focalflow_filtering) && !pc.isFilteringPaused(), "same local action explicitly resumes");
    check(!trees.isFilteringActive() && !trees.hasCapture(), "resume never resurrects old tree; needs fresh capture");
    check(!FocalFlowMenuActions.announce(context, pipeline, pauseNotice), "queued old pause announcement cannot supersede resume");
    check(!context.getSharedPreferences("focalflow_recovery", Context.MODE_PRIVATE).getBoolean("paused", true), "explicit resume updates stored preference");
    ProtocolTestSupport.connect(); pc.beginCapture(); check(ProtocolTestSupport.capture(tree()), "resumed new capture");
    CompletableFuture<JSONObject> fresh = pc.requestUiUpdate(null); JSONObject freshRequest = ProtocolTestSupport.last();
    ProtocolTestSupport.raw(ProtocolTestSupport.response(freshRequest, filtered()).toString());
    check(fresh.isDone() && !fresh.isCompletedExceptionally() && trees.isFilteringActive(), "resumed current valid result can activate filtering");
    error(old); check(trees.isFilteringActive(), "old pre-pause error cannot clear resumed result");
    pc.beginCapture(); JSONObject zero = tree(); zero.remove("children"); zero.put("isVirtualFocusNode", false);
    check(ProtocolTestSupport.capture(zero), "zero-focus source remains structurally valid");
    CompletableFuture<JSONObject> empty = pc.requestUiUpdate(null); JSONObject zeroRequest = ProtocolTestSupport.last();
    ProtocolTestSupport.raw(ProtocolTestSupport.response(zeroRequest, zero).toString());
    check(empty.isDone() && !empty.isCompletedExceptionally() && !trees.isFilteringActive(), "source-zero response is valid data with native bypass, not a failure or forced true flag");
    check(lastNotice().state == PcConnectionManager.RecoveryState.NATIVE, "zero-focus feedback is informational rather than failure");
    check(original.equals(originalSource.toString()), "actual submitted source retained unchanged through recovery");
    publisher.closeTransport();
    check(!FocalFlowMenuActions.handle(-1), "other menu actions remain untouched");
    pc.setRecoveryFeedback(null); pc.disconnect();
    try (java.util.stream.Stream<Path> paths = Files.walk(temp)) {
      for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path);
    }
    check(networkAttempts == 0, "local recovery performs zero network/cloud calls");
    System.out.println("local_recovery_checks=" + checks + " failures=0 network_attempts=" + networkAttempts + " native_audio=NOT_RUN");
  }
  static JSONObject allFalse(JSONObject tree) {
    java.util.ArrayList<JSONObject> nodes = new java.util.ArrayList<>(); nodes.add(tree);
    for (int i=0;i<nodes.size();i++) {
      JSONObject node=nodes.get(i); node.put("isVirtualFocusNode", false); JSONObject children=node.optJSONObject("children");
      if(children!=null) for(String key:children.keySet()) nodes.add(children.getJSONObject(key));
    }
    return tree;
  }
}
