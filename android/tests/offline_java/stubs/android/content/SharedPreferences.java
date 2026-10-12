package android.content;
public interface SharedPreferences {
  boolean getBoolean(String key, boolean fallback);
  Editor edit();
  interface Editor { Editor putBoolean(String key, boolean value); void apply(); }
}
