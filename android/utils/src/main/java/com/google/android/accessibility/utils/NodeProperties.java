package com.google.android.accessibility.utils;

import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONException;
import org.json.JSONObject;

/** Shared wire properties for one node; traversal, identity and focus stay with the callers. */
final class NodeProperties {
  private NodeProperties() {}

  static void write(AccessibilityNodeInfo node, JSONObject jsonNode) throws JSONException {
    // 基本属性 - 与ui_elements_log格式完全一致
    jsonNode.put("className", node.getClassName() == null ? JSONObject.NULL : node.getClassName().toString());
    jsonNode.put("text", node.getText() == null ? JSONObject.NULL : node.getText().toString());
    jsonNode.put(
        "contentDescription",
        node.getContentDescription() == null
            ? JSONObject.NULL
            : node.getContentDescription().toString());
    jsonNode.put(
        "viewIdResourceName",
        node.getViewIdResourceName() == null ? JSONObject.NULL : node.getViewIdResourceName());

    // 交互性属性 - 与ui_elements_log格式完全一致
    jsonNode.put("isClickable", node.isClickable());
    jsonNode.put("isCheckable", node.isCheckable());
    jsonNode.put("isChecked", node.isChecked());
    jsonNode.put("isFocusable", node.isFocusable());
    jsonNode.put("isEnabled", node.isEnabled());
    jsonNode.put("isPassword", node.isPassword());
    jsonNode.put("isSelected", node.isSelected());

    // 位置信息 - 与ui_elements_log格式完全一致
    Rect bounds = new Rect();
    node.getBoundsInScreen(bounds);
    int centerX = bounds.centerX();
    int centerY = bounds.centerY();
    jsonNode.put("centerCoordinates", centerX + "," + centerY);

    JSONObject boundsJson = new JSONObject();
    boundsJson.put("left", bounds.left);
    boundsJson.put("top", bounds.top);
    boundsJson.put("right", bounds.right);
    boundsJson.put("bottom", bounds.bottom);
    jsonNode.put("bounds", boundsJson);
  }
}
