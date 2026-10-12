package com.google.android.accessibility.utils;

/** Initial finite policies; constructor injection permits deterministic lifecycle tests. */
public final class ConnectionLimits {
  public final int requestMillis, connectMillis, writeMillis, frameMillis, attempts, retryMillis;
  public ConnectionLimits() { this(120000, 5000, 5000, 30000, 3, 1000); }
  public ConnectionLimits(int request, int connect, int write, int frame, int attempts, int retry) {
    if (request <= 0 || connect <= 0 || write <= 0 || frame <= 0 || retry <= 0 || attempts < 1 || attempts > 3)
      throw new IllegalArgumentException("Invalid connection limits");
    this.requestMillis = request; this.connectMillis = connect; this.writeMillis = write;
    this.frameMillis = frame; this.attempts = attempts; this.retryMillis = retry;
  }
}
