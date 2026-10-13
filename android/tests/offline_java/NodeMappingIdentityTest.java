package com.google.android.accessibility.utils;

import android.content.Context;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;
import java.util.UUID;
import org.json.JSONObject;

/** Real mapping, builder and focus filter; synthetic native identity and focusability. */
public final class NodeMappingIdentityTest {
  private static final VirtualTreeManager trees = VirtualTreeManager.getInstance();
  private static int checks;
  private static int failures;
  private static void check(boolean condition, String message) {
    checks++;
    if (!condition) { failures++; System.out.println("FAIL " + message); }
  }
  private static AccessibilityNodeInfo node(String text) {
    AccessibilityNodeInfo node = new AccessibilityNodeInfo();
    node.state.text = text;
    return node;
  }
  private static AccessibilityNodeInfoCompat wrap(AccessibilityNodeInfo node) {
    return AccessibilityNodeInfoCompat.wrap(node);
  }
  private static JSONObject find(JSONObject tree, String text) {
    if (text.equals(tree.optString("text"))) return tree;
    JSONObject children = tree.optJSONObject("children");
    if (children != null) for (String key : children.keySet()) {
      JSONObject found = find(children.getJSONObject(key), text);
      if (found != null) return found;
    }
    return null;
  }
  private static boolean focus(AccessibilityNodeInfo node) {
    return FocusProxy.getInstance().shouldFocusNode(wrap(node));
  }
  private static JSONObject publish(NodeMappingManager mapping, AccessibilityNodeInfo a,
      AccessibilityNodeInfo b) {
    AccessibilityNodeInfo root = node("synthetic-root");
    root.state.viewId = "synthetic:root";
    root.add(a); root.add(b);
    SnapshotContext context = new SnapshotContext(UUID.randomUUID().toString(), 1, 1);
    trees.invalidate(context);
    JSONObject tree = VirtualTreeBuilder.buildVirtualTree(root, null, mapping);
    check(trees.captureVirtualTree(context, tree), "capture accepted");
    JSONObject filtered = new JSONObject(tree.toString());
    find(filtered, "synthetic-selected").put("isVirtualFocusNode", true);
    find(filtered, "synthetic-excluded").put("isVirtualFocusNode", false);
    check(trees.registerRequest(context, "synthetic-request", false), "request accepted");
    check(trees.applyFilteredVirtualTree(context, "synthetic-request", filtered), "filter applied");
    trees.finishRequest(context, "synthetic-request", true);
    return filtered;
  }
  @SuppressWarnings("unchecked")
  private static AccessibilityNodeInfoCompat owned(NodeMappingManager mapping, String id)
      throws Exception {
    Field field = NodeMappingManager.class.getDeclaredField("virtualToActualNodeMap");
    field.setAccessible(true);
    return ((Map<String, AccessibilityNodeInfoCompat>) field.get(mapping)).get(id);
  }
  private static void focusIdentity(Path path, boolean missingUid, boolean differentBounds)
      throws Exception {
    FocusProxy.cleanup();
    AccessibilityNodeInfoCompat.forceNoUniqueId = missingUid;
    NodeMappingManager mapping = new NodeMappingManager(new Context(path.toFile()));
    FocusProxy.initialize(mapping, trees);
    AccessibilityNodeInfo a = node("synthetic-selected"), b = node("synthetic-excluded");
    if (differentBounds) { b.state.left = 20; b.state.right = 30; }
    JSONObject filtered = publish(mapping, a, b);
    String aId = find(filtered, "synthetic-selected").getString("virtualNodeId");
    String bId = find(filtered, "synthetic-excluded").getString("virtualNodeId");
    String key = NodeMappingManager.generateActualNodeGlobalId(wrap(a));
    check(aId.equals(mapping.getVirtualNodeId(wrap(a))), "selected native retains own UUID");
    check(bId.equals(mapping.getVirtualNodeId(wrap(b))), "excluded native retains own UUID");
    check(focus(a) && !focus(b), "selected focus survives distinct native with same attributes");
    AccessibilityNodeInfo clone = AccessibilityNodeInfo.obtain(a);
    check(aId.equals(mapping.getVirtualNodeId(wrap(clone))) && focus(clone),
        "fresh native clone resolves selected identity");
    clone.recycle();
    if (missingUid && !differentBounds) {
      check(mapping.getVirtualNodeId(key) == null, "ambiguous property key returns no UUID");
      AccessibilityNodeInfo unknown = node("synthetic-unmapped");
      int before = AccessibilityNodeInfoUtils.fallbackCalls;
      check(focus(unknown) && AccessibilityNodeInfoUtils.fallbackCalls == before + 1,
          "unmapped native with identical properties preserves native acceptance");
      AccessibilityNodeInfoUtils.originalResult = false;
      before = AccessibilityNodeInfoUtils.fallbackCalls;
      check(!focus(unknown) && AccessibilityNodeInfoUtils.fallbackCalls == before + 1,
          "unmapped native preserves native rejection");
      AccessibilityNodeInfoUtils.originalResult = true;
    } else {
      check(aId.equals(mapping.getVirtualNodeId(key)), "unambiguous global key remains usable");
    }
    // Property drift cannot turn an excluded native into its selected neighbour.
    b.state.left = a.state.left; b.state.right = a.state.right;
    a.state.left = 50; a.state.right = 60;
    check(aId.equals(mapping.getVirtualNodeId(wrap(a))) && focus(a) && !focus(b),
        "native identity survives mutable attributes");
    AccessibilityNodeInfoCompat caller = mapping.getActualNode(aId);
    check(caller != null && caller != owned(mapping, aId), "actual lookup gives caller a copy");
    if (caller != null) caller.recycle();
    check(aId.equals(mapping.getVirtualNodeId(wrap(a))), "caller recycle leaves owned key valid");
    mapping.removeMappingByActualNode(wrap(a));
    check(mapping.getVirtualNodeId(wrap(a)) == null && bId.equals(mapping.getVirtualNodeId(wrap(b))),
        "remove by native cannot delete colliding neighbour");
    FocusProxy.cleanup();
  }
  private static void lifecycle(Path path) throws Exception {
    AccessibilityNodeInfoCompat.forceNoUniqueId = true;
    NodeMappingManager mapping = new NodeMappingManager(new Context(path.toFile()));
    AccessibilityNodeInfo a = node("synthetic-a"), b = node("synthetic-b");
    AccessibilityNodeInfoCompat caller = wrap(a);
    mapping.addMapping("old-capture", caller);
    AccessibilityNodeInfoCompat old = owned(mapping, "old-capture");
    mapping.addMapping("new-capture", wrap(a));
    AccessibilityNodeInfoCompat current = owned(mapping, "new-capture");
    mapping.removeMappingByVirtualId("old-capture");
    check(old.recycles == 1 && caller.recycles == 0, "remove recycles owned handle only");
    check("new-capture".equals(mapping.getVirtualNodeId(wrap(a))),
        "removing older alias cannot delete or recycle latest reverse key");
    mapping.addMapping("new-capture", wrap(b));
    check(current.recycles == 1 && mapping.getVirtualNodeId(wrap(a)) == null
        && "new-capture".equals(mapping.getVirtualNodeId(wrap(b))),
        "rebinding UUID removes old native reverse entry before recycle");
    mapping.addMapping("other", wrap(a));
    b.state.valid = false;
    check(mapping.getActualNode("new-capture") == null
        && mapping.getVirtualNodeId(wrap(b)) == null
        && "other".equals(mapping.getVirtualNodeId(wrap(a))),
        "invalid handle removal preserves collision neighbour");
    AccessibilityNodeInfoCompat cleared = owned(mapping, "other");
    mapping.clearAllMappings();
    check(cleared.recycles == 1 && mapping.getVirtualNodeId(wrap(a)) == null,
        "clear releases handles and reverse entries");
    mapping.addMapping("after-clear", wrap(a));
    check("after-clear".equals(mapping.getVirtualNodeId(wrap(a))), "open owner reusable after clear");
    mapping.close();
    mapping.addMapping("retired", wrap(b));
    check(mapping.getVirtualNodeId(wrap(a)) == null && mapping.getVirtualNodeId(wrap(b)) == null,
        "closed owner rejects late capture writes");
    NodeMappingManager replacement = new NodeMappingManager(new Context(path.resolve("new-owner").toFile()));
    VirtualTreeBuilder.buildVirtualTree(a, null, mapping);
    check(replacement.getVirtualNodeId(wrap(a)) == null && mapping.getVirtualNodeId(wrap(a)) == null,
        "retired builder cannot populate replacement owner");
    replacement.close();
  }
  public static void main(String[] args) throws Exception {
    Path path = Files.createDirectories(Paths.get(args[0]));
    System.setSecurityManager(new SecurityManager() {
      @Override public void checkPermission(java.security.Permission permission) {}
      @Override public void checkConnect(String host, int port) { throw new AssertionError("network forbidden"); }
    });
    focusIdentity(path.resolve("collision"), true, false);
    focusIdentity(path.resolve("bounds"), true, true);
    focusIdentity(path.resolve("uid"), false, false);
    lifecycle(path.resolve("lifecycle"));
    AccessibilityNodeInfoCompat.forceNoUniqueId = false;
    System.out.println("mapping_identity_checks=" + checks + " failures=" + failures
        + " production=REAL_MAP_BUILDER_FILTER hash=REAL platform=SYNTHETIC network=NONE");
    if (failures != 0) throw new AssertionError("mapping identity regression failures=" + failures);
  }
}
