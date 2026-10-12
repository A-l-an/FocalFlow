import com.google.android.accessibility.utils.*;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import android.content.Context;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import org.json.*;

/** Actual request registration/receiver/final-manager monitor; no phone/network/model. */
public class FreshnessTest {
  static final PcConnectionManager pc = ProtocolTestSupport.pc;
  static final VirtualTreeManager trees = ProtocolTestSupport.trees;
  static String fixture;
  static int checks;
  static void check(boolean value, String label) { checks++; if (!value) throw new AssertionError(label); }
  static JSONObject tree() { return new JSONObject(fixture); }
  static JSONObject title(JSONObject root) { return root.getJSONObject("children").getJSONObject("element-card").getJSONObject("children").getJSONObject("element-title"); }
  static JSONObject opposite() { JSONObject result = tree(); title(result).put("isVirtualFocusNode", false); return result; }
  static JSONObject last() { return ProtocolTestSupport.last(); }
  static void receive(JSONObject request, Object payload) throws Exception { ProtocolTestSupport.raw(ProtocolTestSupport.response(request, payload).toString()); }
  static void prepare() throws Exception { ProtocolTestSupport.connect(); pc.beginCapture(); check(ProtocolTestSupport.capture(tree()), "current capture"); }
  static void expire(JSONObject request) throws Exception {
    Method method = PcConnectionManager.class.getDeclaredMethod("expire", SnapshotContext.class, String.class);
    method.setAccessible(true); method.invoke(pc, SnapshotContext.parse(request.getJSONObject("context")), request.getString("requestId"));
  }
  static int pending() throws Exception { Field field = PcConnectionManager.class.getDeclaredField("pendingRequests"); field.setAccessible(true); return ((Map<?, ?>) field.get(pc)).size(); }
  public static void main(String[] args) throws Exception {
    fixture = Files.readString(Path.of(args[0]));
    System.setSecurityManager(new SecurityManager() {
      @Override public void checkPermission(java.security.Permission permission) { }
      @Override public void checkConnect(String host, int port) { throw new AssertionError("Network forbidden"); }
    });
    JSONArray vectors = new JSONArray(Files.readString(Path.of(args[0]).resolveSibling("protocol_vectors.json")));
    for (int i = 0; i < vectors.length(); i++) {
      JSONObject vector = vectors.getJSONObject(i); boolean accepted;
      try { SnapshotContext.header(vector.getJSONObject("message")); accepted = true; }
      catch (IllegalArgumentException error) { accepted = false; }
      check(accepted == vector.getBoolean("accepted"), "shared strict vector " + vector.getString("name"));
    }
    prepare();
    CompletableFuture<JSONObject> expired = pc.requestUiUpdate(null); JSONObject old = last();
    expire(old);
    check(expired.isCompletedExceptionally() && pending() == 0, "timeout removes ownership");
    check(trees.getVirtualTreeRoot() == null, "timeout switches to native fallback");
    check("INVALIDATE_CONTEXT".equals(last().getString("type")), "timeout sends backend cancellation");
    check(ProtocolTestSupport.capture(tree()), "same raw source recaptured after timeout");
    CompletableFuture<JSONObject> current = pc.requestUiUpdate(null); JSONObject latest = last();
    receive(latest, opposite());
    check(!current.isCompletedExceptionally() && !title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "new result applies");
    receive(old, tree());
    check(!title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "late expired result cannot overwrite opposite flags");
    JSONObject unknown = ProtocolTestSupport.response(latest, tree()).put("requestId", "unknown");
    ProtocolTestSupport.raw(unknown.toString());
    ProtocolTestSupport.raw(new JSONObject().put("type", "UI_UPDATE").put("payload", tree()).toString());
    check(!title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "unknown and missing-context legacy push rejected");

    prepare();
    CompletableFuture<JSONObject> a = pc.requestUiUpdate(null); JSONObject requestA = last();
    CompletableFuture<JSONObject> b = pc.requestUiUpdate(null);
    check(!a.isDone() && b.isCompletedExceptionally() && pending() == 1, "busy UI request does not supersede A");
    receive(requestA, opposite());
    check(a.isDone() && !a.isCompletedExceptionally(), "active request completes before successor admission");
    b = pc.requestUiUpdate(null); JSONObject requestB = last();
    expire(requestA);
    check(pending() == 1 && !b.isDone(), "old timeout cannot cancel successor");
    receive(requestB, opposite()); receive(requestA, tree());
    check(b.isDone() && !b.isCompletedExceptionally() && !title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "late old response cannot undo B");

    prepare(); pc.requestUiUpdate(null); JSONObject queued = last();
    CountDownLatch started = new CountDownLatch(1); AtomicReference<Throwable> failure = new AtomicReference<>();
    Thread receiver;
    synchronized (trees) {
      receiver = new Thread(() -> { started.countDown(); try { receive(queued, opposite()); } catch (Throwable error) { failure.set(error); } });
      receiver.start(); check(started.await(2, TimeUnit.SECONDS), "receiver queued before commit monitor");
      pc.invalidateContext(); check(ProtocolTestSupport.capture(tree()), "new context published before queued apply lock released");
    }
    receiver.join(2000);
    check(!receiver.isAlive() && failure.get() == null && title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "receiver rechecks freshness at actual commit monitor");
    check(!trees.applyFilteredVirtualTree(SnapshotContext.parse(queued.getJSONObject("context")), queued.getString("requestId"), opposite()), "manager itself rejects stale final apply");

    SnapshotContext captureA = pc.beginCapture(); SnapshotContext captureB = pc.beginCapture();
    check(!trees.captureVirtualTree(captureA, tree()) && trees.getVirtualTreeRoot() == null, "stale builder cannot reactivate filtering");
    check(!trees.captureVirtualTree(captureB, new JSONObject()) && trees.getVirtualTreeRoot() == null, "failed builder cannot resurrect prior tree");
    Path mappingDirectory = Files.createTempDirectory("synthetic-mapping-");
    NodeMappingManager mapping = new NodeMappingManager(new Context(mappingDirectory.toFile()));
    FocusProxy.cleanup(); FocusProxy.initialize(mapping, trees);
    AccessibilityNodeInfoCompat handle = new AccessibilityNodeInfoCompat("synthetic");
    mapping.addMapping(title(tree()).getString("virtualNodeId"), handle);
    int fallback = AccessibilityNodeInfoUtils.fallbackCalls;
    FocusProxy.getInstance().shouldFocusNode(handle);
    check(AccessibilityNodeInfoUtils.fallbackCalls == fallback + 1, "partial new mapping cannot affect native fallback during capture");
    check(trees.captureVirtualTree(captureB, tree()), "latest completed capture accepted");

    CompletableFuture<JSONObject> cancel = pc.requestUiUpdate(null); long seq = pc.currentContext().snapshotSeq;
    cancel.cancel(false);
    check(pending() == 0 && pc.currentContext().snapshotSeq == seq + 1 && trees.getVirtualTreeRoot() == null, "Future cancellation clears ownership and invalidates backend");
    prepare(); pc.requestUiUpdate(null); JSONObject previousTask = last();
    long epoch = pc.currentContext().taskEpoch;
    ReadyTestSupport.role(pc,ProtocolTestSupport.wire,()->{},"synthetic","restarted");
    check(pc.currentContext().taskEpoch == epoch + 1 && pending() == 0 && trees.getVirtualTreeRoot() == null, "ROLE resets task even on same user task identifiers");
    pc.beginCapture(); ProtocolTestSupport.capture(tree()); receive(previousTask, opposite());
    check(title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "old task reply rejected");
    pc.requestUiUpdate(null); JSONObject previousSession = last(); String session = pc.currentContext().sessionId;
    Method restart = PcConnectionManager.class.getDeclaredMethod("startSession"); restart.setAccessible(true); restart.invoke(pc);
    check(!session.equals(pc.currentContext().sessionId) && pending() == 0, "reconnect creates fresh UUID and clears pending");
    pc.beginCapture(); ProtocolTestSupport.capture(tree()); receive(previousSession, opposite());
    check(title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "old-session packet rejected");

    prepare(); CompletableFuture<JSONObject> decision = pc.requestUiUpdate(null); JSONObject base = last();
    check(pc.requestTalk().isCompletedExceptionally() && pending() == 1, "busy Talk rejected without stealing Decision ownership");
    receive(base, opposite()); check(decision.isDone() && !decision.isCompletedExceptionally(), "normal positive current result applies");
    CompletableFuture<JSONObject> talk = pc.requestTalk(); JSONObject talkRequest = last();
    check(talkRequest.getString("baseRequestId").equals(base.getString("requestId")), "Talk explicitly depends on valid classification");
    receive(talkRequest, tree()); check(talk.isDone() && !talk.isCompletedExceptionally() && title(trees.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "positive current Talk applies");
    CompletableFuture<JSONObject> noop = pc.requestTalk(); JSONObject noRequest = last();
    ProtocolTestSupport.raw(SnapshotContext.parse(noRequest.getJSONObject("context")).message("TALK_RESPONSE", noRequest.getString("requestId")).put("status", "NO_OP").toString());
    check(noop.isDone() && !noop.isCompletedExceptionally() && pending() == 0, "Talk A no-op is successful and leaves focus");
    Field timers = PcConnectionManager.class.getDeclaredField("timer"); timers.setAccessible(true);
    check(((ScheduledThreadPoolExecutor) timers.get(pc)).getQueue().size() == 0, "completed futures leave no scheduled timeout backlog");
    pc.invalidateContext(); check(pc.requestTalk().isCompletedExceptionally(), "same-window change invalidates Talk base");

    if (args.length == 3) bridge(args[1], args[2]);
    pc.disconnect();
    try (java.util.stream.Stream<Path> paths = Files.walk(mappingDirectory)) {
      for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path);
    }
    System.out.println("freshness_checks=" + checks + " failures=0 network_attempts=0");
  }
  static void bridge(String backend, String python) throws Exception {
    prepare(); CompletableFuture<JSONObject> future = pc.requestUiUpdate(null); JSONObject request = last();
    Path temp = Files.createTempDirectory("focalflow-wire-"); Path input = temp.resolve("java.json"), output = temp.resolve("python.json");
    try {
      Files.writeString(input, new JSONObject().put("request", request).put("snapshot", pc.currentContext().envelope(tree())).toString());
      Process process = new ProcessBuilder(python, "-m", "tests.protocol_bridge", input.toString(), output.toString()).directory(new java.io.File(backend)).inheritIO().start();
      check(process.waitFor() == 0, "Python production admission consumes Java request and snapshot envelope");
      ProtocolTestSupport.raw(Files.readString(output));
      check(future.isDone() && !future.isCompletedExceptionally(), "Java production receiver applies Python production response");
      check(!trees.getVirtualTreeRoot().getJSONObject("children").getJSONObject("element-other").getBoolean("isVirtualFocusNode"), "cross-language flags preserved");
    } finally { Files.deleteIfExists(input); Files.deleteIfExists(output); Files.deleteIfExists(temp); }
  }
}
