package com.google.android.accessibility.utils;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;
import java.io.*;
import java.net.Socket;
import java.net.InetSocketAddress;
import java.net.SocketTimeoutException;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.LongSupplier;
import org.json.JSONObject;
import org.checkerframework.checker.nullness.qual.Nullable;

/** Versioned, bounded request transport. The tree manager is the final commit lock. */
public class PcConnectionManager {
  private static final String TAG = "PcConnectionManager";
  private static PcConnectionManager instance;
  private final VirtualTreeManager trees = VirtualTreeManager.getInstance();
  private final Map<String, CompletableFuture<JSONObject>> pendingRequests = new HashMap<>();
  private final Map<String, ScheduledFuture<?>> timeouts = new HashMap<>();
  public enum RecoveryState { PAUSED, RESUMED, FAILED, NATIVE, WAITING, CONNECTED }
  public interface RecoveryFeedback { void onRecovery(RecoveryNotice notice); }
  public static final class RecoveryNotice {
    public final RecoveryState state;
    private final SnapshotContext context;
    private final long revision;
    private RecoveryNotice(RecoveryState state, SnapshotContext context, long revision) {
      this.state = state; this.context = context; this.revision = revision;
    }
  }
  /** Separate from page/speech revisions: only a newer service cycle revokes auto-off. */
  public static final class ServiceExitNotice {
    private final long generation;
    private boolean consumed;
    private ServiceExitNotice(long generation) { this.generation = generation; }
  }
  private java.util.function.Consumer<ServiceExitNotice> serviceExitFeedback;
  private long serviceGeneration;
  public void setServiceExitFeedback(java.util.function.Consumer<ServiceExitNotice> feedback) {
    synchronized (trees) { serviceExitFeedback = feedback; }
  }
  /** Called by the service main queue. A delayed old EOF cannot disable a new session. */
  public void runServiceExit(ServiceExitNotice notice, Runnable disableService) {
    synchronized (trees) {
      if (notice == null || notice.consumed || notice.generation != serviceGeneration || isConnected) return;
      notice.consumed = true;
      FocusProxy.cleanup();
      disableService.run();
    }
  }
  private volatile RecoveryFeedback recoveryFeedback;
  private long recoveryRevision;
  private volatile boolean connectRequested;
  private boolean captureAfterConnect;
  private boolean resumeConnectPending;
  private SharedPreferences recoveryPreferences;

  /** Listener must only enqueue/coalesce local UI work, never perform blocking speech/IO here. */
  public void setRecoveryFeedback(RecoveryFeedback feedback) { recoveryFeedback = feedback; }
  public boolean isFilteringPaused() { return trees.isPaused(); }
  public boolean isRecoveryNoticeCurrent(RecoveryNotice notice) {
    synchronized (trees) { return notice != null && notice.revision == recoveryRevision && notice.context.equals(current); }
  }
  private void notifyRecovery(RecoveryState state) {
    RecoveryNotice notice = new RecoveryNotice(state, current, ++recoveryRevision);
    RecoveryFeedback feedback = recoveryFeedback;
    if (feedback != null) feedback.onRecovery(notice);
  }
  public void pauseFiltering() {
    final PrintWriter previous;
    synchronized (trees) {
      if (trees.isPaused()) return;
      serviceGeneration++;
      current = new SnapshotContext(current.sessionId, current.taskEpoch, current.snapshotSeq + 1);
      trees.setPaused(true);
      if (recoveryPreferences != null) recoveryPreferences.edit().putBoolean("paused", true).apply();
      invalidateLocal();
      previous = writer;
      connectRequested = false;
      captureAfterConnect = false;
      resumeConnectPending = false;
    }
    // EOF cancels the backend even when a queued initial ROLE was never sent.
    // Do not take the synchronized(this) disconnect lock while holding trees.
    closeConnection(previous);
    synchronized (trees) { if (trees.isPaused()) notifyRecovery(RecoveryState.PAUSED); }
  }
  public void resumeFiltering() {
    synchronized (trees) {
      if (!trees.isPaused()) return;
      trees.setPaused(false);
      if (recoveryPreferences != null) recoveryPreferences.edit().putBoolean("paused", false).apply();
      current = new SnapshotContext(current.sessionId, current.taskEpoch, current.snapshotSeq + 1);
      invalidateLocal();
      captureAfterConnect = true;
      resumeConnectPending = true;
      notifyRecovery(RecoveryState.RESUMED);
    }
  }


  /** Resume execution is independent of discardable speech-notice generations. */
  public synchronized void runPendingResume() {
    synchronized (trees) {
      if (!resumeConnectPending || trees.isPaused()) return;
      resumeConnectPending = false;
      if (isConnected) return;
    }
    connect();
  }
  public boolean isResumeCapturePending() {
    synchronized (trees) { return captureAfterConnect && !trees.isPaused(); }
  }

  private ScheduledThreadPoolExecutor timer;
  private final LongSupplier nowMillis;
  private final ConnectionLimits limits;
  private final int port;
  private boolean hasDispatchedCapture;
  private long lastCaptureDispatchMillis;
  private ScheduledFuture<?> trailingCapture;
  private Object trailingIntent;
  private CompletableFuture<JSONObject> trailingCompletion;

  private ExecutorService writerExecutor;
  private Socket socket;
  private PrintWriter writer;
  private InputStream reader;
  private Thread connectionThread;
  // TCP transport can exist while ADB reverse has no desktop listener yet.
  private volatile boolean isConnected;
  private volatile boolean backendReady;
  private boolean sessionEstablished;
  private String pendingRoleId;
  private SnapshotContext pendingRoleContext;
  private volatile long roleDeadlineMillis;
  private volatile boolean shouldStop;
  private SnapshotContext current = new SnapshotContext(UUID.randomUUID().toString(), 1, 0);
  private String userId = "User_12", taskId = "Task_3";

  private PcConnectionManager() { this(() -> System.nanoTime() / 1000000L, null); }
  PcConnectionManager(LongSupplier nowMillis, ScheduledThreadPoolExecutor scheduler) {
    this(nowMillis, scheduler, new ConnectionLimits(), 9998);
  }
  PcConnectionManager(LongSupplier nowMillis, ScheduledThreadPoolExecutor scheduler, ConnectionLimits limits, int port) {
    if (port < 1 || port > 65535) throw new IllegalArgumentException("Invalid loopback port");
    this.limits = limits; this.port = port;
    this.nowMillis = nowMillis;
    this.timer = scheduler;
    if (timer != null) timer.setRemoveOnCancelPolicy(true);
    trees.invalidate(current);
  }
  public static synchronized PcConnectionManager getInstance() {
    if (instance == null) instance = new PcConnectionManager();
    return instance;
  }
  public void initialize(Context context) {
    SharedPreferences preferences = context.getApplicationContext().getSharedPreferences("focalflow_recovery", Context.MODE_PRIVATE);
    boolean saved = preferences.getBoolean("paused", false);
    synchronized (trees) {
      recoveryPreferences = preferences;
      serviceGeneration++;
      trees.setPaused(saved);
      invalidateLocal();
    }
  }
  public boolean isConnected() { return isConnected && backendReady; }

  public synchronized void connect() {
    if (trees.isPaused()) return;
    if (connectionThread != null) {
      if (!isConnected) connectRequested = true;
      return;
    }
    connectRequested = false;
    shouldStop = false;
    synchronized (trees) {
      serviceGeneration++;
      captureAfterConnect = true;
      invalidateLocal();
      notifyRecovery(RecoveryState.WAITING);
    }
    writerExecutor = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
        new ArrayBlockingQueue<Runnable>(32));
    connectionThread = new Thread(this::connectionLoop, "PcConnectionThread");
    connectionThread.start();
  }

  public synchronized void disconnect() {
    shouldStop = true;
    connectRequested = false;
    synchronized (trees) { serviceGeneration++; }
    synchronized (trees) {
      resumeConnectPending = false; captureAfterConnect = false;
      // Revoke in-flight local capture tokens even when no socket/capture was published yet.
      current = new SnapshotContext(current.sessionId, current.taskEpoch, current.snapshotSeq + 1);
      invalidateLocal();
    }
    closeConnection();
    FocusProxy.cleanup();
    if (writerExecutor != null) { writerExecutor.shutdownNow(); writerExecutor = null; }
    synchronized (trees) {
      if (timer != null) { timer.shutdownNow(); timer = null; }
    }
    if (connectionThread != null) connectionThread.interrupt();
  }

  private void connectionLoop() {
    try {
      // Before the first connection, wait locally until the desktop starts or the
      // user disables/pauses. Each connect and the retry delay remain bounded.
      while (!shouldStop && !trees.isPaused()) {
        try {
          Socket connected = new Socket();
          // Publish the owned connecting socket so disconnect can interrupt connect.
          synchronized (trees) {
            if (shouldStop) { connected.close(); return; }
            socket = connected;
          }
          connected.connect(new InetSocketAddress("127.0.0.1", port), limits.connectMillis);
          connected.setSoTimeout(Math.min(200, limits.frameMillis));
          synchronized (trees) {
            if (shouldStop || trees.isPaused() || socket != connected) { connected.close(); return; }
            writer = new PrintWriter(new OutputStreamWriter(connected.getOutputStream(), StandardCharsets.UTF_8), true);
            reader = connected.getInputStream();
            isConnected = true;
            startSession();
          }
          messageReceiveLoop();
          if (shouldStop || trees.isPaused() || connectRequested) return;
        } catch (Exception e) {
          Log.w(TAG, "PC connection failed (" + e.getClass().getSimpleName() + ")");
        } finally { closeConnection(); }
        if (!shouldStop && !trees.isPaused()) Thread.sleep(limits.retryMillis);
      }
    } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    finally {
      synchronized (trees) {
        if (timer != null) { timer.shutdownNow(); timer = null; }
      }
      synchronized (this) {
        if (writerExecutor != null) { writerExecutor.shutdownNow(); writerExecutor = null; }
        if (connectionThread == Thread.currentThread()) connectionThread = null;
        // Consume the explicit restart intent and start its cycle under the same
        // lifecycle lock; a later disconnect cannot be bypassed by a stale local boolean.
        if (connectRequested && !trees.isPaused()) {
          connectRequested = false;
          connect();
        } else connectRequested = false;
      }
    }
  }

  private void startSession() {
    synchronized (trees) {
      current = new SnapshotContext(UUID.randomUUID().toString(), current.taskEpoch + 1, 0);
      invalidateLocal();
      connectRequested = false;
      backendReady = false;
      sessionEstablished = false;
      sendRole();
    }
  }

  private void closeConnection() { closeConnection(null); }

  private void closeConnection(PrintWriter expected) {
    Socket old;
    synchronized (trees) {
      if (expected != null && writer != expected) return;
      if (socket == null && writer == null && reader == null && !isConnected
          && pendingRequests.isEmpty() && trailingCapture == null && !trees.isFilteringActive()
          && !trees.hasCapture()) return;
      boolean endService = isConnected && sessionEstablished && !shouldStop && !trees.isPaused();
      boolean reportFailure = !endService && !trees.isPaused() && (trees.isFilteringActive() || !pendingRequests.isEmpty());
      isConnected = false;
      backendReady = false;
      sessionEstablished = false;
      pendingRoleId = null;
      pendingRoleContext = null;
      roleDeadlineMillis = 0;
      invalidateLocal();
      if (reportFailure) notifyRecovery(RecoveryState.FAILED);
      old = socket;
      socket = null; writer = null; reader = null;
      if (endService) {
        shouldStop = true;
        connectRequested = false;
        resumeConnectPending = false;
        captureAfterConnect = false;
        java.util.function.Consumer<ServiceExitNotice> feedback = serviceExitFeedback;
        if (feedback != null) feedback.accept(new ServiceExitNotice(serviceGeneration));
      }
    }
    // Closing the socket wakes its reader; do not wait on a BufferedReader read lock.
    if (old != null) try { old.close(); } catch (IOException e) { Log.w(TAG, "PC close failed"); }
  }

  private void invalidateLocal() {
    recoveryRevision++;
    cancelTrailingCapture();
    trees.invalidate(current);
    for (ScheduledFuture<?> timeout : timeouts.values()) timeout.cancel(false);
    timeouts.clear();
    List<CompletableFuture<JSONObject>> old = new ArrayList<>(pendingRequests.values());
    pendingRequests.clear();
    for (CompletableFuture<JSONObject> future : old) future.completeExceptionally(new IOException("Context invalidated"));
  }

  /** Called on observation, before slow capture or any native mapping write. */
  public SnapshotContext invalidateContext() {
    synchronized (trees) {
      if (trees.isPaused()) return current;
      current = new SnapshotContext(current.sessionId, current.taskEpoch, current.snapshotSeq + 1);
      invalidateLocal();
      submit(current.message("INVALIDATE_CONTEXT", UUID.randomUUID().toString()), current, null);
      return current;
    }
  }
  public SnapshotContext beginCapture() { synchronized (trees) { return trees.isPaused() ? null : invalidateContext(); } }
  /** Page notifications do not revoke a completed or in-flight capture. */
  public boolean invalidateForEvent(android.view.accessibility.AccessibilityEvent event) { return false; }

  /** Service capture admission waits for the current UI/Talk request without blocking a UI lock. */
  public CompletableFuture<JSONObject> pendingOperation() {
    synchronized (trees) {
      if (trailingCompletion != null) return trailingCompletion;
      if (!pendingRequests.isEmpty()) return pendingRequests.values().iterator().next();
      return CompletableFuture.completedFuture(null);
    }
  }
  public SnapshotContext currentContext() { synchronized (trees) { return current; } }

  public void sendRoleSignal(String user, String task) {
    if (user == null || task == null || !user.matches("[A-Za-z0-9_-]{1,128}") || !task.matches("[A-Za-z0-9_-]{1,128}")) return;
    synchronized (trees) {
      userId = user; taskId = task;
      current = new SnapshotContext(current.sessionId, current.taskEpoch + 1, 0);
      invalidateLocal();
      captureAfterConnect = true;
      if (!trees.isPaused()) sendRole();
    }
  }
  private void sendRole() {
    if (!isConnected || writer == null) return;
    backendReady = false;
    pendingRoleId = UUID.randomUUID().toString();
    pendingRoleContext = current;
    roleDeadlineMillis = nowMillis.getAsLong() + limits.connectMillis;
    submit(SnapshotContext.put(SnapshotContext.put(current.message("ROLE", pendingRoleId), "PID", userId), "TaskID", taskId), current, null);
  }
  public void sendSignal(String type, Map<String, String> data) {
    if ("REQUEST_TALK".equals(type)) requestTalk();
    else if ("ROLE".equals(type) && data != null) sendRoleSignal(data.get("PID"), data.get("TaskID"));
  }
  @Deprecated public void sendUiUpdatedSignal(String timestamp) { invalidateContext(); }

  private static CompletableFuture<JSONObject> failed(Exception error) {
    CompletableFuture<JSONObject> future = new CompletableFuture<>();
    future.completeExceptionally(error);
    return future;
  }
  public CompletableFuture<JSONObject> requestUiUpdate(@Nullable JSONObject interaction) {
    return request(false, interaction);
  }
  public CompletableFuture<JSONObject> requestTalk() { return request(true, null); }

  private CompletableFuture<JSONObject> request(boolean talk, JSONObject interaction) {
    synchronized (trees) {
      if (trees.isPaused()) return failed(new IOException("AI filtering paused"));
      if (!isConnected() || writer == null || writerExecutor == null) {
        trees.withdrawFiltering();
        notifyRecovery(RecoveryState.FAILED);
        return failed(new IOException("PC unavailable"));
      }
      String id = UUID.randomUUID().toString();
      SnapshotContext context = current;
      String base = trees.baseRequest();
      if (!trees.registerRequest(context, id, talk)) return failed(new IOException("No current capture or classification, or busy"));
      recoveryRevision++;
      if (!talk) captureAfterConnect = false;
      // Intent registration and writer submission share this lock and preserve order.
      for (ScheduledFuture<?> timeout : timeouts.values()) timeout.cancel(false);
      timeouts.clear();
      List<CompletableFuture<JSONObject>> old = new ArrayList<>(pendingRequests.values());
      pendingRequests.clear();
      for (CompletableFuture<JSONObject> future : old) future.completeExceptionally(new IOException("Superseded"));
      CompletableFuture<JSONObject> future = new CompletableFuture<>();
      pendingRequests.put(id, future);
      ensureTimer();
      timeouts.put(id, timer.schedule(() -> expire(context, id), limits.requestMillis, TimeUnit.MILLISECONDS));
      future.whenComplete((result, error) -> { if (future.isCancelled()) expire(context, id); });
      JSONObject message = context.message(talk ? "REQUEST_TALK" : "REQUEST_UI_UPDATE", id);
      if (talk) SnapshotContext.put(message, "baseRequestId", base);
      else SnapshotContext.put(message, "interaction", interaction == null ? JSONObject.NULL : interaction);
      submit(message, context, id);
      return future;
    }
  }

  private void ensureTimer() {
    if (timer == null) {
      timer = new ScheduledThreadPoolExecutor(1, r -> { Thread t = new Thread(r, "PcRequestTimeout"); t.setDaemon(true); return t; });
      timer.setRemoveOnCancelPolicy(true);
    }
  }

  private void cancelTrailingCapture() {
    trailingIntent = null;
    if (trailingCapture != null) trailingCapture.cancel(false);
    trailingCapture = null;
    if (trailingCompletion != null) trailingCompletion.completeExceptionally(new IOException("Capture cancelled"));
    trailingCompletion = null;
  }

  /** Preserve the two-second capture request limit, retaining exactly the latest trailing frame. */
  public CompletableFuture<JSONObject> requestCapturedUpdate(SnapshotContext context, @Nullable JSONObject interaction) {
    synchronized (trees) {
      if (trees.isPaused() || !trees.isCurrent(context)) return failed(new IOException("Capture cancelled"));
      if (!isConnected() || writer == null) {
        trees.withdrawFiltering(); notifyRecovery(RecoveryState.FAILED); return failed(new IOException("PC unavailable"));
      }
      cancelTrailingCapture();
      long remaining = hasDispatchedCapture ? 2000 - (nowMillis.getAsLong() - lastCaptureDispatchMillis) : 0;
      if (remaining <= 0) {
        return dispatchCapture(context, interaction);
      }
      final Object intent = new Object();
      trailingIntent = intent;
      final CompletableFuture<JSONObject> completion = new CompletableFuture<>();
      trailingCompletion = completion;
      ensureTimer();
      trailingCapture = timer.schedule(() -> {
        synchronized (trees) {
          if (trailingIntent != intent || trees.isPaused() || !trees.isCurrent(context)) return;
          trailingIntent = null;
          trailingCapture = null;
          trailingCompletion = null;
          dispatchCapture(context, interaction).whenComplete((result, error) -> {
            if (error != null) completion.completeExceptionally(error); else completion.complete(result);
          });
        }
      }, remaining, TimeUnit.MILLISECONDS);
      return completion;
    }
  }

  private CompletableFuture<JSONObject> dispatchCapture(SnapshotContext context, JSONObject interaction) {
    if (!trees.isCurrent(context) || !trees.hasCapture() || !isConnected() || writer == null) return failed(new IOException("Capture unavailable"));
    hasDispatchedCapture = true;
    lastCaptureDispatchMillis = nowMillis.getAsLong();
    return requestUiUpdate(interaction).whenComplete((result, error) -> {
      if (error != null) Log.w(TAG, "REQUEST_UI_UPDATE failed (" + error.getClass().getSimpleName() + ")");
      else Log.d(TAG, "REQUEST_UI_UPDATE completed");
    });
  }

  private void expire(SnapshotContext context, String id) {
    synchronized (trees) {
      if (!trees.ownsRequest(context, id)) return;
      CompletableFuture<JSONObject> future = pendingRequests.get(id);
      if (future != null && !future.isDone()) future.completeExceptionally(new TimeoutException("Request deadline exceeded"));
      // Backend stops future commits/chunks; an already in-flight native call may remain.
      invalidateContext();
      notifyRecovery(RecoveryState.FAILED);
    }
  }

  private void submit(JSONObject message, SnapshotContext context, String id) {
    if (!isConnected || writer == null || writerExecutor == null) return;
    final PrintWriter destination = writer;
    final String type = message.optString("type");
    if (trees.isPaused() && !("INVALIDATE_CONTEXT".equals(type) && context.equals(current))) return;
    final String wire = message.toString();
    if (wire.getBytes(StandardCharsets.UTF_8).length > 65536) { failWriter(destination); return; }
    try {
      writerExecutor.execute(() -> {
        synchronized (trees) {
          if (writer != destination || !isConnected) return;
          if (trees.isPaused() && !("INVALIDATE_CONTEXT".equals(type) && context.equals(current))) return;
          // Controls must remain ordered even if a newer context is already registered.
          if (id != null && !trees.ownsRequest(context, id)) return;
        }
        final Socket ownedSocket;
        final ScheduledFuture<?> watchdog;
        synchronized (trees) {
          if (writer != destination || !isConnected) return;
          ownedSocket = socket;
          ensureTimer();
          watchdog = ownedSocket == null ? null : timer.schedule(() -> {
            // Closing this exact socket interrupts its blocked write; never set a
            // reader timeout from the writer or close a replacement connection.
            try { ownedSocket.close(); } catch (IOException ignored) { }
            failWriter(destination);
          }, limits.writeMillis, TimeUnit.MILLISECONDS);
        }
        try {
          destination.println(wire);
          if (destination.checkError()) failWriter(destination);
        } finally { if (watchdog != null) watchdog.cancel(false); }

      });
    } catch (RejectedExecutionException e) { failWriter(destination); }
  }

  private void failWriter(PrintWriter destination) { closeConnection(destination); }

  private void messageReceiveLoop() {
    final InputStream source = reader;
    final PrintWriter destination = writer;
    ByteArrayOutputStream buffer = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    long frameStarted = 0;
    boolean partial = false;
    try {
      while (isConnected && !shouldStop) {
        if (!backendReady && roleDeadlineMillis != 0 && nowMillis.getAsLong() >= roleDeadlineMillis)
          throw new IOException("Session readiness deadline");
        if (partial && nowMillis.getAsLong() - frameStarted >= limits.frameMillis)
          throw new IOException("Incomplete frame deadline");
        int count;
        try { count = source.read(chunk); }
        catch (SocketTimeoutException timeout) { continue; }
        if (count == -1) {
          if (partial) throw new IOException("Truncated frame");
          break;
        }
        if (count == 0) throw new IOException("No read progress");
        if (partial && nowMillis.getAsLong() - frameStarted >= limits.frameMillis)
          throw new IOException("Incomplete frame deadline");
        for (int i = 0; i < count; i++) {
          if (!partial) { frameStarted = nowMillis.getAsLong(); partial = true; }
          if (chunk[i] == '\n') {
            String message = StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(buffer.toByteArray())).toString().trim();
            buffer.reset(); partial = false;
            if (!message.isEmpty()) processReceivedMessage(message, destination);
          } else {
            if (buffer.size() >= VirtualTreeValidator.MAX_MESSAGE_BYTES) throw new IOException("Wire limit");
            buffer.write(chunk[i]);
          }
        }
      }
    } catch (Exception e) { Log.w(TAG, "PC receive failed (" + e.getClass().getSimpleName() + ")"); }
    finally { closeConnection(destination); }
  }

  private void processReceivedMessage(String message) { processReceivedMessage(message, writer); }

  private void processReceivedMessage(String message, PrintWriter origin) {
    try {
      JSONObject response = VirtualTreeValidator.parseMessage(message);
      SnapshotContext context = SnapshotContext.header(response);
      String id = response.getString("requestId");
      synchronized (trees) {
        if (origin != writer || !isConnected || trees.isPaused()) return;
        if ("SESSION_READY".equals(response.optString("type"))) {
          if (response.length() != 4 || pendingRoleId == null || !pendingRoleId.equals(id)
              || pendingRoleContext == null || !pendingRoleContext.equals(context)
              || !current.equals(context) || nowMillis.getAsLong() >= roleDeadlineMillis) return;
          backendReady = true;
          sessionEstablished = true;
          pendingRoleId = null;
          pendingRoleContext = null;
          roleDeadlineMillis = 0;
          connectRequested = false;
          if (captureAfterConnect) notifyRecovery(RecoveryState.CONNECTED);
          return;
        }
        if (!backendReady) return;
        CompletableFuture<JSONObject> future = pendingRequests.get(id);
        if (future == null || !trees.ownsRequest(context, id)) return;
        boolean decision = trees.baseRequest() == null;
        JSONObject payload = response.optJSONObject("payload");
        boolean noOp = "TALK_RESPONSE".equals(response.optString("type")) && "NO_OP".equals(response.optString("status")) && !decision;
        boolean applied = !response.has("error") && "UI_UPDATE".equals(response.optString("type")) && payload != null
            && trees.applyFilteredVirtualTree(context, id, payload);
        pendingRequests.remove(id);
        ScheduledFuture<?> timeout = timeouts.remove(id);
        if (timeout != null) timeout.cancel(false);
        trees.finishRequest(context, id, applied && trees.isFilteringActive() && decision);
        if (applied || (noOp && !response.has("error") && !response.has("payload"))) {
          recoveryRevision++;
          if (applied && !trees.isFilteringActive()) notifyRecovery(RecoveryState.NATIVE);
          future.complete(applied ? payload : response);
        } else {
          trees.withdrawFiltering();
          notifyRecovery(RecoveryState.FAILED);
          future.completeExceptionally(new IOException("Invalid or failed PC response"));
        }
      }
    } catch (Exception e) { Log.w(TAG, "PC message rejected (" + e.getClass().getSimpleName() + ")"); }
  }
}
