package com.google.android.accessibility.utils;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * One current VAT for the existing ADB pull glob, independent of optional debug history.
 * The staging suffix is not JSON, so the reader cannot discover an incomplete write.
 * Only these two owned files are removed; existing research logs are never migrated or deleted.
 */
final class TransportArtifactStore {
  private final File directory;
  private final File current;
  private final File staging;
  private boolean closed;

  TransportArtifactStore(File baseDirectory) throws IOException {
    directory = new File(baseDirectory, "virtual_tree_logs/User_transport/Task_transport");
    current = new File(directory, "virtual_tree_current.json");
    staging = new File(directory, "virtual_tree_current.tmp");
    clearOwnedFiles();
  }

  synchronized void write(String json) throws IOException {
    if (closed) {
      throw new IOException("Transport store is closed");
    }
    if (!directory.isDirectory() && !directory.mkdirs()) {
      throw new IOException("Cannot create transport directory");
    }
    try {
      try (FileOutputStream output = new FileOutputStream(staging)) {
        output.write(json.getBytes(StandardCharsets.UTF_8));
      }
      // Both files share a filesystem. Android/Linux rename replaces the previous slot atomically.
      if (!staging.renameTo(current)) {
        throw new IOException("Cannot replace transport snapshot");
      }
    } finally {
      remove(staging);
    }
  }

  synchronized void close() throws IOException {
    closed = true;
    clearOwnedFiles();
  }

  private void clearOwnedFiles() throws IOException {
    remove(staging);
    remove(current);
  }

  private static void remove(File file) throws IOException {
    if (file.exists() && !file.delete()) {
      throw new IOException("Cannot remove transport artifact");
    }
  }
}
