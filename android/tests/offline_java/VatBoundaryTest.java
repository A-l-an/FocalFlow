import android.content.Context;
import android.util.Log;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import com.google.android.accessibility.utils.*;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.Permission;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import org.json.JSONObject;

/** Actual validator/manager/receiver/mapping classes; Android node handles are synthetic stubs. */
public final class VatBoundaryTest {
  private static final VirtualTreeManager manager = VirtualTreeManager.getInstance();
  private static final PcConnectionManager pc = PcConnectionManager.getInstance();
  private static String fixture;
  private static Path root;
  private static int checks, failures, networkAttempts;
  private static NodeMappingManager mapping;
  private static Method receive;
  private static final String MARKER = "SYNTHETIC_PRIVATE_SCREEN";

  public static void main(String[] args) throws Exception {
    root = Files.createDirectories(Path.of(args[0]));
    fixture = Files.readString(Path.of(args[1]));
    System.setSecurityManager(new SecurityManager() {
      @Override public void checkPermission(Permission permission) {}
      @Override public void checkConnect(String host, int port) {
        networkAttempts++;
        throw new AssertionError("Unexpected network access");
      }
    });
    mapping = new NodeMappingManager(new Context(root.resolve("mapping").toFile()));
    receive = PcConnectionManager.class.getDeclaredMethod("processReceivedMessage", String.class);
    receive.setAccessible(true);
    run("valid flags preserve immutable capture, metadata, namespace and mapping", VatBoundaryTest::valid);
    run("whole payload mutation matrix rejected atomically before persistence", VatBoundaryTest::mutations);
    run("request response acceptance and rejection complete correctly", VatBoundaryTest::requests);
    run("no source and cleared source reject; zero-focus source retained", VatBoundaryTest::noSource);
    run("10000 node, 128 node-depth and UTF-8 size boundaries", VatBoundaryTest::limits);
    run("malformed, duplicate-key, excessively nested and oversized wire", VatBoundaryTest::wire);
    run("unterminated receive stream is bounded", VatBoundaryTest::stream);
    run("invalid-node fallback logs omit exception text", VatBoundaryTest::focusLog);
    check(networkAttempts == 0, "no network access");
    System.out.println("vat_checks=" + checks + " failures=" + failures + " network_attempts=" + networkAttempts);
    if (failures != 0) throw new AssertionError("VAT boundary regression failed");
  }
  private static JSONObject tree() { return new JSONObject(fixture); }
  private static JSONObject title(JSONObject t) { return t.getJSONObject("children").getJSONObject("element-card").getJSONObject("children").getJSONObject("element-title"); }
  private static JSONObject other(JSONObject t) { return t.getJSONObject("children").getJSONObject("element-other"); }
  private static boolean capture(JSONObject tree) throws Exception { return ProtocolTestSupport.capture(tree); }
  private static boolean apply(JSONObject tree) throws Exception { return ProtocolTestSupport.apply(tree); }
  private static void receive(JSONObject payload) throws Exception { ProtocolTestSupport.receive(payload); }
  private static void raw(String json) throws Exception { receive.invoke(pc, json); }
  private static void prepare() throws Exception {
    ProtocolTestSupport.connect();
    pc.beginCapture();
    manager.setFileLogger(null);
    JSONObject source = tree();
    check(capture(source), "valid synthetic capture accepted");
    for (JSONObject n : nodes(source)) mapping.addMapping(n.getString("virtualNodeId"), new AccessibilityNodeInfoCompat(n.getString("virtualNodeId")));
  }
  private static void valid() throws Exception {
    prepare();
    JSONObject source = tree();
    check(capture(source), "second capture accepted");
    source.put("text", MARKER);
    JSONObject filtered = tree();
    title(filtered).put("isVirtualFocusNode", false);
    Map<String, Object> beforeMapping = mappingState();
    check(apply(filtered), "valid flag change accepted");
    check(!title(manager.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "changed flag reaches display");
    check(manager.getVirtualTreeRoot().isNull("text"), "capture caller cannot mutate trusted source");
    filtered.put("text", MARKER);
    manager.getVirtualTreeRoot().put("text", MARKER);
    manager.findNodeByVirtualId(title(tree()).getString("virtualNodeId")).put("text", MARKER);
    check(apply(tree()), "reapply source flags uses raw capture rather than previous display");
    check(title(manager.getVirtualTreeRoot()).getString("text").equals("Sample item"), "display getters and payload are defensive copies");
    check(!title(manager.getVirtualTreeRoot()).getBoolean("isFocusable") && title(manager.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "native isFocusable is not imposed on virtual flags");
    check(beforeMapping.equals(mappingState()), "real mapping remains unchanged");
    JSONObject withMetadata = tree().put("metadata", new JSONObject().put("quoted", "a\\\"{[b").put("array", new org.json.JSONArray().put(1).put(true).put(JSONObject.NULL)));
    check(capture(withMetadata) && apply(new JSONObject(withMetadata.toString())), "original arbitrary metadata retained without treating it as nodes");
    title(withMetadata).put("isVirtualFocusNode", false);
    receive(withMetadata);
    check(!title(manager.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "wire parses quoted and escaped bracket metadata correctly");
    JSONObject metadataChanged = new JSONObject(withMetadata.toString());
    metadataChanged.getJSONObject("metadata").put("array", new org.json.JSONArray().put(2).put(true).put(JSONObject.NULL));
    rejected(metadataChanged, "existing metadata array changed");
    JSONObject nested = tree(); JSONObject current = nested;
    for (int i = 1; i < 258; i++) { JSONObject next = new JSONObject(); current.put("metadata", next); current = next; }
    current.put("text", "brackets: { [ \" ] }");
    check(capture(nested), "container depth 258 with shallow real-node depth accepted");
    title(nested).put("isVirtualFocusNode", false); receive(nested);
    check(!title(manager.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "wire depth includes envelope but ignores quoted brackets");
  }
  private static void mutations() throws Exception {
    prepare();
    String[] labels = {"unknown UUID", "missing UUID", "duplicate UUID", "malformed UUID", "foreign snapshot UUID", "UUID type", "removed child", "added child", "renamed child key", "swapped node associations", "text", "bounds", "property", "capture metadata", "added field", "removed field", "flag string", "flag number", "flag null", "missing flag", "children array", "child primitive", "bounds flag injection", "children flag injection", "metadata flag injection", "all flags false", "empty object"};
    for (int i = 0; i < labels.length; i++) {
      JSONObject t = tree();
      switch (i) {
        case 0: title(t).put("virtualNodeId", "ffffffff-ffff-4fff-8fff-ffffffffffff"); break;
        case 1: title(t).remove("virtualNodeId"); break;
        case 2: title(t).put("virtualNodeId", other(t).getString("virtualNodeId")); break;
        case 3: title(t).put("virtualNodeId", "broken-reference"); break;
        case 4: t.put("virtualNodeId", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"); break;
        case 5: title(t).put("virtualNodeId", 3); break;
        case 6: t.getJSONObject("children").remove("element-other"); break;
        case 7: t.getJSONObject("children").put("extra", tree()); break;
        case 8: t.getJSONObject("children").put("renamed", t.getJSONObject("children").remove("element-other")); break;
        case 9: String id = title(t).getString("virtualNodeId"); title(t).put("virtualNodeId", other(t).getString("virtualNodeId")); other(t).put("virtualNodeId", id); break;
        case 10: title(t).put("text", MARKER); break;
        case 11: title(t).getJSONObject("bounds").put("right", 99); break;
        case 12: title(t).put("isClickable", true); break;
        case 13: t.put("captureTimestamp", 99); break;
        case 14: title(t).put("added", false); break;
        case 15: title(t).remove("isEnabled"); break;
        case 16: title(t).put("isVirtualFocusNode", "false"); break;
        case 17: title(t).put("isVirtualFocusNode", 0); break;
        case 18: title(t).put("isVirtualFocusNode", JSONObject.NULL); break;
        case 19: title(t).remove("isVirtualFocusNode"); break;
        case 20: t.put("children", new org.json.JSONArray()); break;
        case 21: t.getJSONObject("children").put("element-other", 7); break;
        case 22: title(t).getJSONObject("bounds").put("isVirtualFocusNode", true); break;
        case 23: t.getJSONObject("children").put("isVirtualFocusNode", true); break;
        case 24: t.put("metadata", new JSONObject().put("isVirtualFocusNode", true)); break;
        case 25: for (JSONObject n : nodes(t)) n.put("isVirtualFocusNode", false); break;
        case 26: t = new JSONObject(); break;
      }
      rejected(t, labels[i]);
    }
    check(!capture(tree().put("virtualNodeId", "broken-reference")), "invalid capture identity rejected");
    JSONObject aliases = tree();
    aliases.getJSONObject("children").getJSONObject("element-card").getJSONObject("children").put("element-other", leaf(500));
    check(!capture(aliases), "duplicate child alias in capture rejected");
    check(apply(tree()), "bad capture did not replace trusted source");
  }
  private static void rejected(JSONObject candidate, String label) throws Exception {
    Path dir = Files.createTempDirectory(root, "rejected-");
    FileLogger logger = new FileLogger(new Context(dir.toFile()));
    logger.enableLogType("pc_updated_virtual_tree_logs");
    manager.setFileLogger(logger);
    String before = manager.getVirtualTreeRoot().toString();
    Map<String, Object> beforeMapping = mappingState();
    Log.captured.setLength(0);
    receive(candidate);
    check(before.equals(manager.getVirtualTreeRoot().toString()), label + ": prior display unchanged");
    check(beforeMapping.equals(mappingState()), label + ": mapping unchanged");
    try (var files = Files.walk(dir)) { check(files.noneMatch(Files::isRegularFile), label + ": rejected payload not saved"); }
    check(!Log.captured.toString().contains(MARKER), label + ": error omits payload");
  }
  @SuppressWarnings("unchecked")
  private static void requests() throws Exception {
    prepare();
    ProtocolTestSupport.connect();
    CompletableFuture<JSONObject> good = pc.requestUiUpdate(null);
    JSONObject request = ProtocolTestSupport.last();
    JSONObject filtered = tree(); title(filtered).put("isVirtualFocusNode", false);
    raw(ProtocolTestSupport.response(request, filtered).toString());
    check(good.isDone() && !good.isCompletedExceptionally() && !title(manager.getVirtualTreeRoot()).getBoolean("isVirtualFocusNode"), "valid correlated response applied and completed");
    String before = manager.getVirtualTreeRoot().toString();
    for (Object payload : new Object[] { tree().put("text", MARKER), "wrong-type", JSONObject.NULL }) {
      CompletableFuture<JSONObject> bad = pc.requestUiUpdate(null);
      raw(ProtocolTestSupport.response(ProtocolTestSupport.last(), payload).toString());
      check(bad.isCompletedExceptionally() && before.equals(manager.getVirtualTreeRoot().toString()), "invalid correlated response fails without replacing display");
    }
  }

  private static void noSource() throws Exception {
    manager.clearVirtualTree();
    check(!apply(tree()) && manager.getVirtualTreeRoot() == null, "no source rejected");
    check(capture(tree()), "source captured"); manager.clearVirtualTree();
    check(!apply(tree()), "clear removes source and display");
    JSONObject emptyFocus = leaf(999); emptyFocus.put("isVirtualFocusNode", false);
    check(capture(emptyFocus) && apply(new JSONObject(emptyFocus.toString())), "unchanged zero-focus source accepted without inferring native traversability");
  }
  private static JSONObject leaf(int id) {
    JSONObject n = title(tree());
    n.put("virtualNodeId", String.format("00000000-0000-4000-8000-%012x", id));
    return n;
  }
  private static JSONObject chain(int depth) {
    JSONObject t = leaf(1), cur = t;
    for (int i = 2; i <= depth; i++) { JSONObject next = leaf(i); cur.put("children", new JSONObject().put("depth-" + i, next)); cur = next; }
    return t;
  }
  private static void limits() throws Exception {
    manager.setFileLogger(null);
    JSONObject deep = chain(128);
    check(capture(deep) && apply(new JSONObject(deep.toString())), "node depth 128 accepted");
    JSONObject tooDeep = chain(129);
    String before = manager.getVirtualTreeRoot().toString();
    check(!capture(tooDeep) && !apply(tooDeep), "node depth 129 rejected");
    check(before.equals(manager.getVirtualTreeRoot().toString()) && apply(deep), "depth rejection preserves capture and display");
    rejected(tooDeep, "wire depth 129");
    JSONObject wide = leaf(1); JSONObject children = new JSONObject(); wide.put("children", children);
    for (int i = 2; i <= 10000; i++) children.put("wide-" + i, leaf(i));
    check(capture(wide) && apply(new JSONObject(wide.toString())), "10000 nodes accepted");
    children.put("overflow", leaf(10001));
    before = manager.getVirtualTreeRoot().toString();
    check(!capture(wide) && !apply(wide), "10001 nodes rejected");
    check(before.equals(manager.getVirtualTreeRoot().toString()), "node-count rejection preserves display");
    rejected(wide, "wire node count 10001");
    JSONObject sized = leaf(1).put("text", "");
    int padding = 8 * 1024 * 1024 - sized.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
    sized.put("text", "X".repeat(padding));
    check(capture(sized) && apply(new JSONObject(sized.toString())), "exactly 8 MiB serialized tree accepted");
    sized.put("text", "X".repeat(padding + 1));
    before = manager.getVirtualTreeRoot().toString();
    check(!capture(sized) && !apply(sized), "8 MiB plus one byte rejected");
    check(before.equals(manager.getVirtualTreeRoot().toString()), "size rejection preserves display");
    rejected(sized, "wire size 8 MiB plus one");
    sized.put("text", "界".repeat(padding / 3 + 1));
    check(!capture(sized), "UTF-8 byte limit rather than character count");
    prepare();
  }
  private static void wire() throws Exception {
    prepare();
    JSONObject filtered = tree(); title(filtered).put("isVirtualFocusNode", false); apply(filtered);
    String before = manager.getVirtualTreeRoot().toString();
    String valid = new JSONObject().put("type", "UI_UPDATE").put("payload", tree()).toString();
    String[] inputs = {"{malformed:" + MARKER, "{\"type\":\"UI_UPDATE\",\"type\":\"UI_UPDATE\",\"payload\":" + tree() + "}", "{\"type\":\"UI_UPDATE\",\"payload\":" + "[".repeat(3000) + "0" + "]".repeat(3000) + "}", valid + "trailing", "{\"type\":\"UI_UPDATE\",\"payload\":\"" + "X".repeat(9 * 1024 * 1024) + "\"}"};
    for (String input : inputs) { raw(input); check(before.equals(manager.getVirtualTreeRoot().toString()), "invalid raw message leaves display intact"); }
    check(!Log.captured.toString().contains(MARKER), "wire parse errors omit payload");
  }
  private static void stream() throws Exception {
    prepare();
    String before = manager.getVirtualTreeRoot().toString();
    final int[] consumed = {0};
    java.io.InputStream input = new java.io.InputStream() {
      public int read(byte[] buffer, int offset, int count) {
        if (consumed[0] >= 20 * 1024 * 1024) return -1;
        Arrays.fill(buffer, offset, offset + count, (byte) 'X'); consumed[0] += count; return count;
      }
      public int read() { throw new UnsupportedOperationException(); }
      public void close() {}
    };
    for (String name : new String[] {"isConnected", "shouldStop", "reader"}) {
      Field field = PcConnectionManager.class.getDeclaredField(name); field.setAccessible(true);
      field.set(pc, name.equals("reader") ? input : name.equals("isConnected"));
    }
    Method loop = PcConnectionManager.class.getDeclaredMethod("messageReceiveLoop"); loop.setAccessible(true); loop.invoke(pc);
    check(consumed[0] < 9 * 1024 * 1024, "receive loop stops before buffering unterminated oversized stream");
    check(manager.getVirtualTreeRoot() == null, "oversized stream disconnect clears filtering and ownership");
  }
  private static void focusLog() throws Exception {
    FocusProxy.cleanup(); FocusProxy.initialize(mapping, manager);
    AccessibilityNodeInfoCompat invalid = new AccessibilityNodeInfoCompat("synthetic"); invalid.failAccess = true;
    Log.captured.setLength(0);
    int calls = AccessibilityNodeInfoUtils.fallbackCalls;
    FocusProxy.getInstance().shouldFocusNode(invalid);
    check(AccessibilityNodeInfoUtils.fallbackCalls == calls + 1, "existing invalid-node fallback still called");
    check(!Log.captured.toString().contains(MARKER), "invalid-node exception text not logged");
  }
  private static List<JSONObject> nodes(JSONObject root) {
    List<JSONObject> list = new ArrayList<>(); list.add(root);
    for (int i = 0; i < list.size(); i++) { JSONObject cs = list.get(i).optJSONObject("children"); if (cs != null) for (String key : cs.keySet()) list.add(cs.getJSONObject(key)); }
    return list;
  }
  private static Map<String, Object> mappingState() throws Exception {
    Map<String, Object> result = new HashMap<>();
    for (String name : new String[] {"virtualToActualNodeMap", "actualToVirtualNodeMap", "virtualToActualGlobalIdMap"}) {
      Field f = NodeMappingManager.class.getDeclaredField(name); f.setAccessible(true);
      result.put(name, new HashMap<>((Map<?, ?>) f.get(mapping)));
    }
    return result;
  }
  private static void check(boolean condition, String message) { checks++; if (!condition) throw new AssertionError(message); }
  private interface Test { void run() throws Exception; }
  private static void run(String name, Test test) { try { test.run(); System.out.println("PASS " + name); } catch (Throwable e) { failures++; System.out.println("FAIL " + name + ": " + e.getClass().getSimpleName() + (e instanceof AssertionError ? " " + e.getMessage() : "")); } }
}
