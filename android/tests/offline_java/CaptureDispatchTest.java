package com.google.android.accessibility.utils;

import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

/** Fake monotonic clock/manual scheduler around production capture admission and writer ordering. */
public final class CaptureDispatchTest {
  static int checks;
  static void check(boolean value, String label) { checks++; if (!value) throw new AssertionError(label); }
  static class Task implements ScheduledFuture<Object> {
    final Runnable action;
    final long due;
    boolean cancelled;
    Task(Runnable action, long due) { this.action = action; this.due = due; }
    public boolean cancel(boolean interrupt) { cancelled = true; return true; }
    public boolean isCancelled() { return cancelled; }
    public boolean isDone() { return cancelled; }
    public Object get() { throw new UnsupportedOperationException(); }
    public Object get(long timeout, TimeUnit unit) { throw new UnsupportedOperationException(); }
    public long getDelay(TimeUnit unit) { return unit.convert(due, TimeUnit.MILLISECONDS); }
    public int compareTo(Delayed other) { return Long.compare(getDelay(TimeUnit.MILLISECONDS), other.getDelay(TimeUnit.MILLISECONDS)); }
    void force() { action.run(); }
  }
  static class Scheduler extends ScheduledThreadPoolExecutor {
    final long[] now;
    final List<Task> tasks = new ArrayList<>();
    Scheduler(long[] now) { super(1); this.now = now; }
    @Override public ScheduledFuture<?> schedule(Runnable action, long delay, TimeUnit unit) {
      Task task = new Task(action, now[0] + unit.toMillis(delay)); tasks.add(task); return task;
    }
    Task last() { return tasks.get(tasks.size() - 1); }
    long liveTrailing() { return tasks.stream().filter(t -> !t.cancelled && t.due <= now[0] + 2000).count(); }
  }
  static class WriterQueue extends AbstractExecutorService {
    final Queue<Runnable> tasks = new ArrayDeque<>();
    public void execute(Runnable task) { tasks.add(task); }
    public void shutdown() { }
    public List<Runnable> shutdownNow() { tasks.clear(); return Collections.emptyList(); }
    public boolean isShutdown() { return false; }
    public boolean isTerminated() { return false; }
    public boolean awaitTermination(long time, TimeUnit unit) { return true; }
    void flush() { while (!tasks.isEmpty()) tasks.remove().run(); }
  }
  static void set(PcConnectionManager pc, String field, Object value) throws Exception {
    Field f = PcConnectionManager.class.getDeclaredField(field); f.setAccessible(true); f.set(pc, value);
  }
  static List<JSONObject> messages(StringWriter wire) {
    List<JSONObject> result = new ArrayList<>();
    for (String line : wire.toString().split("\n")) if (!line.isEmpty()) result.add(new JSONObject(line));
    return result;
  }
  static long requests(StringWriter wire) { return messages(wire).stream().filter(m -> "REQUEST_UI_UPDATE".equals(m.getString("type"))).count(); }
  static void capture(PcConnectionManager pc, JSONObject source) {
    SnapshotContext context = pc.beginCapture();
    check(VirtualTreeManager.getInstance().captureVirtualTree(context, source), "current synthetic capture accepted");
    pc.requestCapturedUpdate(context, source);
  }
  public static void main(String[] args) throws Exception {
    long[] now = {1000}; Scheduler scheduler = new Scheduler(now);
    PcConnectionManager pc = new PcConnectionManager(() -> now[0], scheduler);
    WriterQueue writer = new WriterQueue(); StringWriter wire = new StringWriter();
    set(pc, "isConnected", true); set(pc, "writer", new PrintWriter(wire)); set(pc, "writerExecutor", writer);
    JSONObject source = new JSONObject(Files.readString(Path.of(args[0])));
    ReadyTestSupport.role(pc,wire,writer::flush,"synthetic","task"); capture(pc, source);
    check(messages(wire).size()==1 && "ROLE".equals(messages(wire).get(0).getString("type")), "only acknowledged ROLE is on wire before capture queue flush");
    writer.flush(); List<JSONObject> startup = messages(wire);
    check(startup.size() == 3 && "ROLE".equals(startup.get(0).getString("type")) && "INVALIDATE_CONTEXT".equals(startup.get(1).getString("type")) && "REQUEST_UI_UPDATE".equals(startup.get(2).getString("type")), "startup ROLE survives snapshot advance and precedes capture request");
    check(requests(wire) == 1, "first capture dispatches at leading edge");
    now[0] = 1200; capture(pc, source); Task replaced = scheduler.last(); writer.flush();
    check(requests(wire) == 1 && replaced.due == 3000, "second capture deferred to original two-second boundary");
    now[0] = 1500; capture(pc, source); Task latest = scheduler.last(); SnapshotContext newest = pc.currentContext(); writer.flush();
    check(replaced.cancelled && scheduler.liveTrailing() == 1 && latest.due == 3000, "burst retains only latest trailing capture without moving deadline");
    replaced.force(); writer.flush(); check(requests(wire) == 1, "cancelled old callback cannot dispatch newer or older context");
    now[0] = 3000; latest.force(); writer.flush();
    check(requests(wire) == 2, "latest frame eventually dispatches once at limit");
    JSONObject lastRequest = messages(wire).get(messages(wire).size() - 1);
    check(SnapshotContext.header(lastRequest).equals(newest), "trailing request binds final burst context");
    latest.force(); writer.flush(); check(requests(wire) == 2, "consumed callback cannot send twice");
    now[0] = 3100; capture(pc, source); Task cancelled = scheduler.last();
    pc.invalidateContext(); now[0] = 5000; cancelled.force(); writer.flush();
    check(requests(wire) == 2 && cancelled.cancelled, "new generation without publication cancels pending send");
    now[0] = 6000; capture(pc, source); writer.flush(); check(requests(wire) == 3, "later current capture retains leading dispatch");
    now[0] = 6100; capture(pc, source); Task disconnected = scheduler.last();
    pc.disconnect(); now[0] = 8000; disconnected.force(); writer.flush();
    check(requests(wire) == 3 && disconnected.cancelled, "disconnect cancels trailing dispatch and all pending ownership");
    System.out.println("capture_dispatch_checks=" + checks + " failures=0 fake_clock=true network_attempts=0");
  }
}
