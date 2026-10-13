package androidx.core.view.accessibility;
import android.view.accessibility.AccessibilityNodeInfo;
/** Synthetic handles only: no Android accessibility traversal is modeled. */
public class AccessibilityNodeInfoCompat {
  private final String id;
  public static boolean forceNoUniqueId;
  private AccessibilityNodeInfo node;
  public static AccessibilityNodeInfoCompat wrap(AccessibilityNodeInfo node) { AccessibilityNodeInfoCompat result=new AccessibilityNodeInfoCompat(node.getUniqueId()); result.node=node; return result; }
  public boolean failAccess;
  public CharSequence text;
  public int recycles;
  public AccessibilityNodeInfoCompat(String id) { this.id = id; }
  public static AccessibilityNodeInfoCompat obtain(AccessibilityNodeInfoCompat node) {
    AccessibilityNodeInfoCompat result=new AccessibilityNodeInfoCompat(node.id); result.node=node.node; result.text=node.text; return result;
  }
  public int getWindowId() { return node == null ? 1 : node.getWindowId(); }
  public String getUniqueId() {
    if (failAccess) throw new IllegalStateException("SYNTHETIC_PRIVATE_SCREEN");
    return forceNoUniqueId ? null : id;
  }
  public AccessibilityNodeInfo unwrap() { return node; }
  public boolean refresh() { return node == null || node.refresh(); }
  @Override public boolean equals(Object other) {
    if (this == other) return true;
    if (!(other instanceof AccessibilityNodeInfoCompat)) return false;
    AccessibilityNodeInfoCompat that = (AccessibilityNodeInfoCompat) other;
    if (recycles != 0 || that.recycles != 0) return false;
    return node != null ? node.equals(that.node) : that.node == null && java.util.Objects.equals(id, that.id);
  }
  @Override public int hashCode() { return recycles != 0 ? 0 : node != null ? node.hashCode() : java.util.Objects.hashCode(id); }
  public void recycle() { recycles++; }
  public CharSequence getText() { return node == null ? text : node.getText(); }
  public CharSequence getContentDescription() { return null; }
}
