package androidx.core.view.accessibility;
import android.view.accessibility.AccessibilityNodeInfo;
/** Synthetic handles only: no Android accessibility traversal is modeled. */
public class AccessibilityNodeInfoCompat {
  private final String id;
  private AccessibilityNodeInfo node;
  public static AccessibilityNodeInfoCompat wrap(AccessibilityNodeInfo node) { AccessibilityNodeInfoCompat result=new AccessibilityNodeInfoCompat(Integer.toString(System.identityHashCode(node))); result.node=node; return result; }
  public boolean failAccess;
  public CharSequence text;
  public int recycles;
  public AccessibilityNodeInfoCompat(String id) { this.id = id; }
  public static AccessibilityNodeInfoCompat obtain(AccessibilityNodeInfoCompat node) {
    AccessibilityNodeInfoCompat result=new AccessibilityNodeInfoCompat(node.id); result.node=node.node; result.text=node.text; return result;
  }
  public int getWindowId() { return 1; }
  public String getUniqueId() {
    if (failAccess) throw new IllegalStateException("SYNTHETIC_PRIVATE_SCREEN");
    return id;
  }
  public AccessibilityNodeInfo unwrap() { return node; }
  public boolean refresh() { return true; }
  public void recycle() { recycles++; }
  public CharSequence getText() { return node == null ? text : node.getText(); }
  public CharSequence getContentDescription() { return null; }
}
