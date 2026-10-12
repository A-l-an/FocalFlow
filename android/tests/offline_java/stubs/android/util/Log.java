package android.util;

/** Captures actual production logging calls for synthetic marker assertions. */
public final class Log {
  public static final StringBuilder captured = new StringBuilder();
  private static int record(String message, Throwable error) {
    captured.append(message).append('\n');
    if (error != null) captured.append(error.toString()).append('\n');
    return 0;
  }
  public static int d(String tag, String message) { return record(message, null); }
  public static int i(String tag, String message) { return record(message, null); }
  public static int w(String tag, String message) { return record(message, null); }
  public static int e(String tag, String message) { return record(message, null); }
  public static int w(String tag, String message, Throwable error) { return record(message, error); }
  public static int e(String tag, String message, Throwable error) { return record(message, error); }
}
