package com.google.android.libraries.accessibility.utils.log;

import android.util.Log;

public final class LogUtils {
  private static String format(String message, Object... args) {
    String result = String.format(message, args);
    for (Object arg : args) if (arg instanceof Throwable) result += arg.toString();
    return result;
  }
  // Production defaults to ERROR. Debug/warning output needs explicit diagnostic opt-in.
  public static void v(String tag, String message, Object... args) {}
  public static void d(String tag, String message, Object... args) {}
  public static void w(String tag, String message, Object... args) {}
  public static void e(String tag, String message, Object... args) { Log.e(tag, format(message, args)); }
}
