package android.content;

import java.io.File;

/** Only the storage API used by FileLogger; this is not an Android runtime. */
public class Context {
  public static final int MODE_PRIVATE = 0;
  private static final java.util.Map<String, java.util.Map<String, Boolean>> preferences = new java.util.HashMap<>();
  private final File root;
  public Context(File root) { this.root = root; }
  public Context getApplicationContext() { return this; }
  public File getExternalFilesDir(String type) { return root; }
  public File getFilesDir() { return root; }
  public String getString(int resource) { return "resource:" + resource; }
  public SharedPreferences getSharedPreferences(String name, int mode) {
    String identity = root.getAbsolutePath() + "/" + name;
    final java.util.Map<String, Boolean> data;
    synchronized (preferences) { data = preferences.computeIfAbsent(identity, key -> new java.util.HashMap<>()); }
    return new SharedPreferences() {
      public boolean getBoolean(String key, boolean fallback) { return data.getOrDefault(key, fallback); }
      public Editor edit() { return new Editor() {
        public Editor putBoolean(String key, boolean value) { data.put(key, value); return this; }
        public void apply() { }
      }; }
    };
  }
}
