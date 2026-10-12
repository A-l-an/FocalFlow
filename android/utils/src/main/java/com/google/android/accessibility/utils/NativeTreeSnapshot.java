package com.google.android.accessibility.utils;

import android.graphics.Rect;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import org.json.JSONObject;

/** Immutable native identity/attribute evidence from one local builder traversal. */
public final class NativeTreeSnapshot implements AutoCloseable {
  private static final int MAX_EVENT_NODES = 64;
  private static final long MAX_EVENT_MILLIS = 12;
  private static final String[] FIELDS = {"className", "text", "contentDescription",
      "viewIdResourceName", "isClickable", "isCheckable", "isChecked", "isFocusable",
      "isEnabled", "isPassword", "isSelected"};
  private final Map<AccessibilityNodeInfo, Entry> entries = new HashMap<>();
  private boolean valid = true, sealed;
  private long bytes;

  static final class Entry {
    final AccessibilityNodeInfo identity;
    final Entry parent;
    final int index, count;
    final ArrayList<Object> values;
    final ArrayList<Entry> children = new ArrayList<>();
    Entry(AccessibilityNodeInfo node, Entry parent, ArrayList<Object> values) {
      identity = AccessibilityNodeInfo.obtain(node);
      this.parent = parent;
      index = parent == null ? 0 : parent.children.size();
      count = node.getChildCount();
      this.values = values;
    }
  }

  // Called during the very traversal that creates the JSON and UUID mapping.
  Entry record(AccessibilityNodeInfo node, JSONObject json, Entry parent, int depth) {
    if (!valid) return null;
    try {
      if (sealed || depth > VirtualTreeValidator.MAX_NODE_DEPTH
          || entries.size() >= VirtualTreeValidator.MAX_NODES || entries.containsKey(node)) {
        close(); return null;
      }
      ArrayList<Object> values = new ArrayList<>();
      for (String field : FIELDS) {
        Object value = json.get(field);
        values.add(value == JSONObject.NULL ? null : value);
      }
      JSONObject bounds = json.getJSONObject("bounds");
      for (String side : new String[]{"left", "top", "right", "bottom"}) values.add(bounds.getInt(side));
      appendNativeValues(values, node);
      for (Object value : values) {
        if (value instanceof String) bytes += ((String) value).getBytes(StandardCharsets.UTF_8).length;
      }
      if (bytes > VirtualTreeValidator.MAX_TREE_BYTES) { close(); return null; }
      Entry entry = new Entry(node, parent, values);
      entries.put(entry.identity, entry);
      if (parent != null) parent.children.add(entry);
      return entry;
    } catch (Exception error) {
      close(); return null;
    }
  }

  void seal() {
    if (entries.isEmpty()) { close(); return; }
    for (Entry entry : entries.values()) {
      if (entry.count != entry.children.size()) { close(); return; }
    }
    sealed = true;
  }

  private static String text(CharSequence value) { return value == null ? null : value.toString(); }

  private static void appendNativeValues(ArrayList<Object> values, AccessibilityNodeInfo node) {
    values.add(node.isVisibleToUser()); values.add(node.isScrollable());
    values.add(text(node.getPackageName())); values.add(node.getWindowId());
  }

  private static ArrayList<Object> readValues(AccessibilityNodeInfo node) {
    ArrayList<Object> values = new ArrayList<>();
    values.add(text(node.getClassName())); values.add(text(node.getText()));
    values.add(text(node.getContentDescription())); values.add(node.getViewIdResourceName());
    values.add(node.isClickable()); values.add(node.isCheckable()); values.add(node.isChecked());
    values.add(node.isFocusable()); values.add(node.isEnabled()); values.add(node.isPassword());
    values.add(node.isSelected());
    Rect bounds = new Rect(); node.getBoundsInScreen(bounds);
    values.add(bounds.left); values.add(bounds.top); values.add(bounds.right); values.add(bounds.bottom);
    appendNativeValues(values, node);
    return values;
  }

  private static final class Budget {
    final long deadline = SystemClock.uptimeMillis() + MAX_EVENT_MILLIS;
    int nodes;
    boolean current() { return SystemClock.uptimeMillis() <= deadline; }
    boolean take() { return ++nodes <= MAX_EVENT_NODES && current(); }
  }

  private boolean sameNode(AccessibilityNodeInfo node, Entry entry, Budget budget) {
    return node != null && entry != null && budget.take() && entry.identity.equals(node)
        && node.refresh() && entry.count == node.getChildCount()
        && entry.values.equals(readValues(node)) && budget.current();
  }

  private boolean sameSubtree(AccessibilityNodeInfo node, Entry entry, Budget budget) {
    if (!sameNode(node, entry, budget)) return false;
    for (int i = 0; i < entry.children.size(); i++) {
      if (!budget.current()) return false;
      AccessibilityNodeInfo child = node.getChild(i);
      try {
        if (!sameSubtree(child, entry.children.get(i), budget)) return false;
      } finally {
        if (child != null) child.recycle();
      }
    }
    return true;
  }

  /** Only explicit text/description events have a scope this evidence can establish. */
  boolean unchanged(AccessibilityEvent event) {
    int mask = event.getContentChangeTypes();
    int known = AccessibilityEvent.CONTENT_CHANGE_TYPE_TEXT
        | AccessibilityEvent.CONTENT_CHANGE_TYPE_CONTENT_DESCRIPTION;
    if (!valid || !sealed || mask == 0 || (mask & ~known) != 0) return false;
    AccessibilityNodeInfo source = null;
    try {
      source = event.getSource();
      Entry entry = entries.get(source);
      if (entry == null || event.getWindowId() != source.getWindowId()
          || !Objects.equals(text(event.getPackageName()), text(source.getPackageName()))) return false;
      Budget budget = new Budget();
      if (!sameSubtree(source, entry, budget)) return false;
      // A cached source must still belong to the same native ancestor chain and child slot.
      // Do not walk siblings: a small text source can belong to a large captured page.
      while (entry.parent != null) {
        AccessibilityNodeInfo parent = source.getParent();
        if (parent == null) return false;
        boolean transferred = false;
        try {
          if (!sameNode(parent, entry.parent, budget)) return false;
          AccessibilityNodeInfo child = parent.getChild(entry.index);
          try { if (child == null || !child.equals(source)) return false; }
          finally { if (child != null) child.recycle(); }
          source.recycle(); source = parent; entry = entry.parent;
          transferred = true;
        } finally {
          if (!transferred) parent.recycle();
        }
      }
      return budget.current();
    } catch (Exception error) {
      return false;
    } finally {
      if (source != null) source.recycle();
    }
  }

  @Override public void close() {
    valid = false; sealed = false;
    for (Entry entry : entries.values()) entry.identity.recycle();
    entries.clear();
  }
}
