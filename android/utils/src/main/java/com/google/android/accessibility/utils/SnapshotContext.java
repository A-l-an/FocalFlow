package com.google.android.accessibility.utils;

import java.util.UUID;
import org.json.JSONObject;
import org.json.JSONException;

/** Immutable, strictly typed protocol v1 context shared by capture and transport. */
public final class SnapshotContext {
  public static final long MAX_COUNTER = 9007199254740991L;
  public final String sessionId;
  public final long taskEpoch;
  public final long snapshotSeq;

  public SnapshotContext(String sessionId, long taskEpoch, long snapshotSeq) {
    if (sessionId == null || !sessionId.matches("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")
        || taskEpoch < 0 || taskEpoch > MAX_COUNTER || snapshotSeq < 0 || snapshotSeq > MAX_COUNTER) {
      throw new IllegalArgumentException("Invalid context");
    }
    this.sessionId = sessionId;
    this.taskEpoch = taskEpoch;
    this.snapshotSeq = snapshotSeq;
  }

  public static SnapshotContext parse(JSONObject value) {
    if (value == null || value.length() != 3 || !(value.opt("sessionId") instanceof String))
      throw new IllegalArgumentException("Invalid context");
    return new SnapshotContext((String) value.opt("sessionId"), counter(value.opt("taskEpoch")), counter(value.opt("snapshotSeq")));
  }

  private static long counter(Object value) {
    if (!(value instanceof Integer) && !(value instanceof Long)) throw new IllegalArgumentException("Invalid counter");
    return ((Number) value).longValue();
  }

  public static SnapshotContext header(JSONObject message) {
    Object version = message.opt("protocolVersion");
    if (!(version instanceof Integer) || ((Integer) version) != 1
        || !(message.opt("requestId") instanceof String)
        || !((String) message.opt("requestId")).matches("[A-Za-z0-9_-]{1,128}")) {
      throw new IllegalArgumentException("Invalid protocol header");
    }
    return parse(message.optJSONObject("context"));
  }

  public static JSONObject put(JSONObject object, String key, Object value) {
    try { return object.put(key, value); }
    catch (JSONException e) { throw new IllegalArgumentException("Invalid protocol JSON"); }
  }
  public JSONObject json() {
    return put(put(put(new JSONObject(), "sessionId", sessionId), "taskEpoch", taskEpoch), "snapshotSeq", snapshotSeq);
  }
  public JSONObject message(String type, String requestId) {
    return put(put(put(put(new JSONObject(), "protocolVersion", 1), "context", json()), "type", type), "requestId", requestId);
  }
  public JSONObject envelope(JSONObject tree) {
    return put(put(put(new JSONObject(), "protocolVersion", 1), "context", json()), "tree", tree);
  }

  /** Pending user intent belongs to the session/task, not an earlier capture sequence. */
  public boolean sameTask(SnapshotContext other) {
    return other != null && sessionId.equals(other.sessionId) && taskEpoch == other.taskEpoch;
  }

  @Override public boolean equals(Object value) {
    if (!(value instanceof SnapshotContext)) return false;
    SnapshotContext other = (SnapshotContext) value;
    return sessionId.equals(other.sessionId) && taskEpoch == other.taskEpoch && snapshotSeq == other.snapshotSeq;
  }
  @Override public int hashCode() { return json().toString().hashCode(); }
}
