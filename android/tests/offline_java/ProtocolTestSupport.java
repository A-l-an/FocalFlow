import com.google.android.accessibility.utils.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.JSONObject;

/** Synthetic transport only; registration, receipt and final application are production code. */
public final class ProtocolTestSupport {
  public static final StringWriter wire = new StringWriter();
  public static final PcConnectionManager pc = PcConnectionManager.getInstance();
  public static final VirtualTreeManager trees = VirtualTreeManager.getInstance();
  public static final ExecutorService direct = new AbstractExecutorService() {
    public void shutdown() { }
    public List<Runnable> shutdownNow() { return Collections.emptyList(); }
    public boolean isShutdown() { return false; }
    public boolean isTerminated() { return false; }
    public boolean awaitTermination(long timeout, TimeUnit unit) { return true; }
    public void execute(Runnable task) { task.run(); }
  };
  public static void set(String name, Object value) throws Exception {
    Field field = PcConnectionManager.class.getDeclaredField(name); field.setAccessible(true); field.set(pc, value);
  }
  public static void connect() throws Exception {
    boolean ready=pc.isConnected();
    set("isConnected", true); set("writer", new PrintWriter(wire)); set("writerExecutor", direct);
    if(!ready) ReadyTestSupport.role(pc,wire,()->{},"synthetic","task");
  }
  public static boolean capture(JSONObject tree) {
    return trees.captureVirtualTree(pc.currentContext(), tree);
  }
  public static boolean apply(JSONObject tree) {
    String id = UUID.randomUUID().toString();
    SnapshotContext context = pc.currentContext();
    if (!trees.registerRequest(context, id, false)) return false;
    boolean result = trees.applyFilteredVirtualTree(context, id, tree);
    trees.finishRequest(context, id, result);
    return result;
  }
  public static JSONObject last() {
    String[] lines = wire.toString().trim().split("\\n");
    return new JSONObject(lines[lines.length - 1]);
  }
  public static JSONObject response(JSONObject request, Object payload) {
    return SnapshotContext.parse(request.getJSONObject("context")).message("UI_UPDATE", request.getString("requestId")).put("payload", payload);
  }
  public static CompletableFuture<JSONObject> receive(JSONObject payload) throws Exception {
    connect();
    CompletableFuture<JSONObject> future = pc.requestUiUpdate(null);
    raw(response(last(), payload).toString());
    return future;
  }
  public static void raw(String json) throws Exception {
    Method receive = PcConnectionManager.class.getDeclaredMethod("processReceivedMessage", String.class);
    receive.setAccessible(true); receive.invoke(pc, json);
  }
}
