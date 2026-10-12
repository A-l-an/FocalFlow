import android.content.Context;
import android.util.Log;
import com.google.android.accessibility.utils.FileLogger;
import com.google.android.accessibility.utils.PcConnectionManager;
import com.google.android.accessibility.utils.VirtualTreeManager;
import java.io.File;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.Permission;
import java.util.Collections;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** Runs real production classes; only Android storage/log output and the wire sink are replaced. */
public final class SensitiveLoggingTest {
  private static final String MARKER = "SYNTHETIC_PRIVATE_SCREEN";
  private static int checks;
  private static int failures;
  private static int networkAttempts;
  private static Path root;
  private static String fixture;

  public static void main(String[] args) throws Exception {
    root = Path.of(args[0]);
    fixture = Files.readString(Path.of(args[1]));
    System.setSecurityManager(new SecurityManager() {
      @Override public void checkPermission(Permission permission) {}
      @Override public void checkConnect(String host, int port) {
        networkAttempts++;
        throw new AssertionError("Unexpected network access");
      }
    });
    run("default persistence and explicit opt-in", SensitiveLoggingTest::persistence);
    run("PC tree logging stays disabled by default", SensitiveLoggingTest::pcTree);
    run("wire payload preserved, Logcat marker absent", SensitiveLoggingTest::wire);
    run("transport slot lifecycle", SensitiveLoggingTest::transport);
    run("untrusted VAT without source is not saved or applied", SensitiveLoggingTest::untrustedWithoutSource);
    check(networkAttempts == 0, "network attempts must be zero");
    System.out.println("checks=" + checks + " failures=" + failures + " network_attempts=" + networkAttempts);
    if (failures != 0) throw new AssertionError("Privacy regression assertions failed");
  }

  private static FileLogger logger(String directory) throws Exception {
    return new FileLogger(new Context(Files.createDirectories(root.resolve(directory)).toFile()));
  }

  private static void persistence() throws Exception {
    FileLogger logger = logger("default");
    JSONObject payload = new JSONObject().put("text", MARKER);
    logger.logTtsSimple(MARKER);
    logger.logText("node_names_log", MARKER);
    logger.logJson("ui_elements_log", payload);
    logger.logJson("virtual_tree_log", payload);
    logger.logJson("ui_interaction_log", payload);
    logger.logOrUpdateUiInteraction(payload);
    check(fileCount(root.resolve("default")) == 0, "default debug logging writes no files");
    logger.enableLogType("tts_logs");
    logger.logTtsSimple(MARKER);
    check(fileCount(root.resolve("default")) == 1, "explicit TTS opt-in writes one file");
    try (var paths = Files.walk(root.resolve("default"))) {
      Path log = paths.filter(Files::isRegularFile).findFirst().get();
      check(Files.readString(log).contains(MARKER), "opt-in debug content retained");
    }
  }

  private static void pcTree() throws Exception {
    FileLogger logger = logger("pc");
    VirtualTreeManager manager = VirtualTreeManager.getInstance();
    manager.setFileLogger(logger);
    ProtocolTestSupport.capture(new JSONObject(fixture).put("text", MARKER));
    ProtocolTestSupport.apply(new JSONObject(fixture).put("text", MARKER));
    check(fileCount(root.resolve("pc")) == 0, "PC tree must not enable persistent logs");
    logger.enableLogType("pc_updated_virtual_tree_logs");
    ProtocolTestSupport.apply(new JSONObject(fixture).put("text", MARKER));
    check(fileCount(root.resolve("pc")) == 1, "explicit PC tree opt-in persists debug tree");
  }

  private static void wire() throws Exception {
    Log.captured.setLength(0);
    PcConnectionManager pc = PcConnectionManager.getInstance();
    Method receive = PcConnectionManager.class.getDeclaredMethod("processReceivedMessage", String.class);
    receive.setAccessible(true);
    JSONObject capture = new JSONObject(fixture).put("text", MARKER);
    ProtocolTestSupport.connect();
    ProtocolTestSupport.capture(capture);
    ProtocolTestSupport.receive(new JSONObject(capture.toString()));
    check(MARKER.equals(VirtualTreeManager.getInstance().getVirtualTreeRoot().getString("text")),
        "incoming tree reaches production memory unchanged");
    receive.invoke(pc, "{malformed:" + MARKER);
    receive.invoke(pc, new JSONObject().put("type", MARKER).toString());
    StringWriter wire = new StringWriter();
    set(pc, "writer", new PrintWriter(wire));
    set(pc, "isConnected", true);
    set(pc, "writerExecutor", ProtocolTestSupport.direct);
    pc.sendRoleSignal(MARKER, "synthetic-task");
    check(MARKER.equals(new JSONObject(wire.toString().trim()).getString("PID")),
        "outgoing ROLE payload preserved");
    set(pc, "writer", null);
    set(pc, "isConnected", false);
    logger("identity").initializeSessionDirectories(MARKER, MARKER);
    check(!Log.captured.toString().contains(MARKER), "Logcat must omit screen, identity and parse-error payloads");
  }

  private static void untrustedWithoutSource() throws Exception {
    FileLogger logger = logger("untrusted");
    logger.enableLogType("pc_updated_virtual_tree_logs");
    VirtualTreeManager manager = VirtualTreeManager.getInstance();
    manager.clearVirtualTree();
    manager.setFileLogger(logger);
    Method receive = PcConnectionManager.class.getDeclaredMethod("processReceivedMessage", String.class);
    receive.setAccessible(true);
    receive.invoke(PcConnectionManager.getInstance(), new JSONObject().put("type", "UI_UPDATE")
        .put("payload", new JSONObject().put("text", MARKER)).toString());
    check(manager.getVirtualTreeRoot() == null && fileCount(root.resolve("untrusted")) == 0,
        "payload without captured source must not be saved or applied");
  }

  private static void transport() throws Exception {
    FileLogger logger = logger("transport");
    Method initialize = requiredMethod("initializeTransport");
    Method publish = requiredMethod("publishVirtualTree", com.google.android.accessibility.utils.SnapshotContext.class, JSONObject.class, JSONObject.class);
    Method close = requiredMethod("closeTransport");
    Path logs = root.resolve("transport/screen_reader_logs");
    Path old = logs.resolve("virtual_tree_logs/User_old/Task_old/old.json");
    Files.createDirectories(old.getParent());
    Files.writeString(old, "SYNTHETIC_PRIOR_RESEARCH");
    initialize.invoke(logger);
    publish.invoke(logger, PcConnectionManager.getInstance().currentContext(), new JSONObject().put("text", MARKER), null);
    Path slot = logs.resolve("virtual_tree_logs/User_transport/Task_transport/virtual_tree_current.json");
    check(new JSONObject(Files.readString(slot)).getJSONObject("tree").getString("text").equals(MARKER), "transport payload unchanged");
    for (int i = 0; i < 20; i++) publish.invoke(logger, PcConnectionManager.getInstance().currentContext(), new JSONObject().put("generation", i), null);
    check(fileCount(slot.getParent()) == 1, "only one operational file remains after repeated writes");
    check(new JSONObject(Files.readString(slot)).getJSONObject("tree").getInt("generation") == 19, "slot holds latest complete JSON");
    check(!Files.readString(slot).contains(MARKER), "prior transport payload replaced");
    check(fileCount(logs) == 2, "default transport creates no debug history");
    AtomicBoolean stop = new AtomicBoolean();
    AtomicInteger reads = new AtomicInteger();
    AtomicReference<Throwable> readFailure = new AtomicReference<>();
    CountDownLatch started = new CountDownLatch(1);
    Thread reader = new Thread(() -> {
      try {
        while (!stop.get()) {
          new JSONObject(Files.readString(slot));
          reads.incrementAndGet();
          started.countDown();
        }
      } catch (Throwable failure) { readFailure.set(failure); started.countDown(); }
    });
    reader.start();
    started.await();
    try {
      for (int i = 0; i < 50; i++) {
        publish.invoke(logger, PcConnectionManager.getInstance().currentContext(), new JSONObject().put("generation", i).put("text", "X".repeat(262144)), null);
      }
    } finally { stop.set(true); reader.join(); }
    check(reads.get() > 0 && readFailure.get() == null, "concurrent reader sees complete old or new JSON");
    check(new JSONObject(Files.readString(slot)).getJSONObject("tree").getInt("generation") == 49, "last replacement completes");
    check(fileCount(slot.getParent()) == 1, "staging file removed after publication");
    // Force an actual storage failure below FileLogger without mocking persistence.
    Files.createDirectory(slot.resolveSibling("virtual_tree_current.tmp"));
    Log.captured.setLength(0);
    publish.invoke(logger, PcConnectionManager.getInstance().currentContext(), new JSONObject().put("text", MARKER), null);
    check(new JSONObject(Files.readString(slot)).getJSONObject("tree").getInt("generation") == 49, "failed write preserves previous complete slot");
    check(!Files.exists(slot.resolveSibling("virtual_tree_current.tmp")), "failed write cleans its staging artifact");
    check(!Log.captured.toString().contains(MARKER), "storage failure logs omit payload");
    close.invoke(logger);
    publish.invoke(logger, PcConnectionManager.getInstance().currentContext(), new JSONObject().put("text", MARKER), null);
    check(!Files.exists(slot), "close removes slot and blocks queued writes");
    check(Files.readString(old).equals("SYNTHETIC_PRIOR_RESEARCH"), "cleanup preserves old research artifacts");
    FileLogger restarted = logger("transport");
    Files.writeString(slot, MARKER);
    Files.writeString(slot.resolveSibling("virtual_tree_current.tmp"), MARKER);
    initialize.invoke(restarted);
    check(fileCount(slot.getParent()) == 0, "restart removes stale owned transport files");
    close.invoke(restarted);
  }

  private static Method requiredMethod(String name, Class<?>... types) {
    try { return FileLogger.class.getMethod(name, types); }
    catch (NoSuchMethodException e) { throw new AssertionError("Missing independent transport lifecycle: " + name); }
  }
  private static long fileCount(Path path) throws Exception {
    try (var paths = Files.walk(path)) { return paths.filter(Files::isRegularFile).count(); }
  }
  private static void set(Object target, String name, Object value) throws Exception {
    Field field = target.getClass().getDeclaredField(name);
    field.setAccessible(true);
    field.set(target, value);
  }
  private static void check(boolean result, String message) {
    checks++;
    if (!result) throw new AssertionError(message);
  }
  private interface Test { void run() throws Exception; }
  private static void run(String name, Test test) {
    try { test.run(); System.out.println("PASS " + name); }
    catch (Throwable failure) { failures++; System.out.println("FAIL " + name + ": " + failure.getMessage()); }
  }
}
