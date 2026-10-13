package com.google.android.accessibility.utils;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
/** No native-focusability assertion: this only identifies that fallback was called. */
public final class AccessibilityNodeInfoUtils {
  public static int fallbackCalls;
  public static boolean originalResult = true;
  private static int nextElement;
  public static String generateUniqueElementId() { return "element-" + (++nextElement); }
  public static boolean shouldFocusNodeOriginal(AccessibilityNodeInfoCompat node) {
    fallbackCalls++;
    return originalResult;
  }
  public static String generateElementHashId(AccessibilityNodeInfo node) { return "synthetic"; }
  public static CountDownLatch hierarchyEntered, hierarchyProceed;
  public static int hierarchyCalls;
  public static RuntimeException hierarchyFailure;
  public static CharSequence getNodeText(AccessibilityNodeInfoCompat node) { return node.getText(); }
  /** Controllable native serialization boundary; never reads actual device nodes. */
  public static JSONObject accessibilityNodeInfoToJson(AccessibilityNodeInfo node) throws org.json.JSONException {
    hierarchyCalls++;
    if (hierarchyFailure != null) throw hierarchyFailure;
    hierarchyEntered.countDown();
    try {
      if (!hierarchyProceed.await(2, TimeUnit.SECONDS)) throw new AssertionError("hierarchy gate timed out");
    } catch (InterruptedException error) { throw new AssertionError(error); }
    return new JSONObject().put("text", "synthetic pause probe");
  }
}
