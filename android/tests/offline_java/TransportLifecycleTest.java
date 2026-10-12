package com.google.android.accessibility.utils;

import android.util.Log;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.concurrent.*;
import org.json.JSONObject;

/** Real production socket loop, framing, watchdog and stop; loopback only. */
public final class TransportLifecycleTest {
  private static int checks;
  private static String fixture;
  private static void check(boolean value, String label) { checks++; if (!value) throw new AssertionError(label); }
  private static JSONObject tree() { return new JSONObject(fixture); }
  private static Object get(PcConnectionManager pc, String name) throws Exception {
    Field field = PcConnectionManager.class.getDeclaredField(name); field.setAccessible(true); return field.get(pc);
  }
  private static void set(PcConnectionManager pc, String name, Object value) throws Exception {
    Field field = PcConnectionManager.class.getDeclaredField(name); field.setAccessible(true); field.set(pc, value);
  }
  private static void failed(CompletableFuture<JSONObject> future) throws Exception {
    try { future.get(2, TimeUnit.SECONDS); throw new AssertionError("Expected failure"); }
    catch (ExecutionException expected) { check(expected.getCause() != null, "explicit future failure"); }
  }
  private static final class Harness implements AutoCloseable {
    final ServerSocket server;
    final Socket peer;
    final PcConnectionManager pc;
    final BufferedReader incoming;
    final Thread connection;
    Harness(ConnectionLimits limits) throws Exception {
      server = new ServerSocket(); server.setReceiveBufferSize(1024);
      server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0)); server.setSoTimeout(2000);
      pc = new PcConnectionManager(() -> System.nanoTime() / 1000000L, null, limits, server.getLocalPort());
      pc.connect(); connection = (Thread) get(pc, "connectionThread");
      peer = server.accept(); peer.setSoTimeout(2000); peer.setReceiveBufferSize(1024);
      incoming = new BufferedReader(new InputStreamReader(peer.getInputStream(), StandardCharsets.UTF_8));
      JSONObject role=next("ROLE");check("ROLE".equals(role.getString("type")), "real connection sends initial ROLE");
      ReadyTestSupport.acknowledge(peer,role);ReadyTestSupport.await(pc);
    }
    JSONObject next(String type) throws Exception {
      String line;
      while ((line = incoming.readLine()) != null) {
        JSONObject message = new JSONObject(line);
        if (type.equals(message.getString("type"))) return message;
      }
      throw new IOException("Peer closed");
    }
    CompletableFuture<JSONObject> request(JSONObject source, JSONObject interaction) throws Exception {
      SnapshotContext capture = pc.beginCapture();
      check(VirtualTreeManager.getInstance().captureVirtualTree(capture, source), "capture bound to live session");
      return pc.requestUiUpdate(interaction);
    }
    void write(byte[] bytes) throws IOException { peer.getOutputStream().write(bytes); peer.getOutputStream().flush(); }
    public void close() throws Exception {
      pc.disconnect(); peer.close(); server.close(); connection.join(2000);
      check(!connection.isAlive(), "disconnect stops owned connection thread");
    }
  }
  private static JSONObject response(JSONObject request, JSONObject payload) {
    return SnapshotContext.parse(request.getJSONObject("context")).message("UI_UPDATE", request.getString("requestId")).put("payload", payload);
  }
  private static void fragmentedAndCoalesced() throws Exception {
    try (Harness h = new Harness(new ConnectionLimits(5000, 500, 500, 2000, 1, 1))) {
      JSONObject source = tree().put("text", "中文");
      CompletableFuture<JSONObject> future = h.request(source, null); JSONObject request = h.next("REQUEST_UI_UPDATE");
      byte[] wire = (response(request, source).toString() + "\n").getBytes(StandardCharsets.UTF_8);
      int split = -1;
      for (int i = 0; i < wire.length; i++) if ((wire[i] & 255) == 0xe4) { split = i + 1; break; }
      check(split > 0, "synthetic UTF8 multibyte boundary found");
      h.peer.getOutputStream().write(wire, 0, split); h.peer.getOutputStream().flush();
      h.peer.getOutputStream().write(wire, split, 1); h.peer.getOutputStream().flush();
      h.peer.getOutputStream().write(wire, split + 1, wire.length - split - 1); h.peer.getOutputStream().flush();
      check("中文".equals(future.get(2, TimeUnit.SECONDS).getString("text")), "split UTF8 byte sequence accepted exactly");
      CompletableFuture<JSONObject> talk = h.pc.requestTalk(); JSONObject talkRequest = h.next("REQUEST_TALK");
      JSONObject unknown = response(request, source).put("requestId", "unknown");
      JSONObject noOp = SnapshotContext.parse(talkRequest.getJSONObject("context")).message("TALK_RESPONSE", talkRequest.getString("requestId")).put("status", "NO_OP");
      h.write((unknown.toString() + "\n" + noOp.toString() + "\n").getBytes(StandardCharsets.UTF_8));
      check("NO_OP".equals(talk.get(2, TimeUnit.SECONDS).getString("status")), "coalesced frames preserve correlated Talk no-op");
    }
  }
  private static void malformedAndEof() throws Exception {
    byte[][] cases = {new byte[] {(byte)0xc3, 0x28, '\n'}, "{\"type\":".getBytes(StandardCharsets.UTF_8), new byte[0]};
    for (int i = 0; i < cases.length; i++) {
      try (Harness h = new Harness(new ConnectionLimits(5000, 500, 500, 80, 1, 1))) {
        CompletableFuture<JSONObject> future = h.request(tree(), null); h.next("REQUEST_UI_UPDATE");
        h.write(cases[i]);
        if (i > 0) h.peer.shutdownOutput();
        failed(future);
        check(!h.pc.isConnected() && VirtualTreeManager.getInstance().getVirtualTreeRoot() == null, "malformed/truncated/EOF invalidates ownership and native filter");
      }
    }
    try (Harness h = new Harness(new ConnectionLimits(5000, 500, 500, 30, 1, 1))) {
      CompletableFuture<JSONObject> future = h.request(tree(), null); h.next("REQUEST_UI_UPDATE");
      h.write(new byte[] {'{'});
      failed(future);
      check(!h.pc.isConnected(), "incomplete real socket frame has finite lifetime");
    }
  }
  private static void writeBackpressureAndIdleStop() throws Exception {
    try (Harness h = new Harness(new ConnectionLimits(5000, 500, 80, 5000, 1, 1))) {
      ((Socket) get(h.pc, "socket")).setSendBufferSize(1024);
      StringBuilder padding = new StringBuilder(); for (int i = 0; i < 64000; i++) padding.append('x');
      CompletableFuture<JSONObject> future = h.request(tree(), new JSONObject().put("text", padding.toString()));
      // Do not read the request: real TCP send buffer/window must backpressure.
      failed(future);
      check(!h.pc.isConnected(), "write watchdog closes the exact blocked socket before request deadline");
    }
    try (Harness h = new Harness(new ConnectionLimits(5000, 500, 500, 5000, 1, 1))) {
      h.pc.disconnect(); h.connection.join(1000);
      check(!h.connection.isAlive(), "idle read is woken by disconnect, not left on socket.read");
    }
  }
  private static void finiteConnectAndLimits() throws Exception {
    int[][] invalid = {{0,1,1,1,1,1},{1,0,1,1,1,1},{1,1,-1,1,1,1},{1,1,1,0,1,1},{1,1,1,1,0,1},{1,1,1,1,4,1},{1,1,1,1,1,0}};
    for (int[] p : invalid) {
      try { new ConnectionLimits(p[0],p[1],p[2],p[3],p[4],p[5]); throw new AssertionError("invalid limit accepted"); }
      catch (IllegalArgumentException expected) { checks++; }
    }
    check(new ConnectionLimits().requestMillis == 120000, "Android and backend request policy both 120 seconds");
    int port;
    try (ServerSocket reserved = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))) { port = reserved.getLocalPort(); }
    PcConnectionManager pc = new PcConnectionManager(() -> System.nanoTime() / 1000000L, null,
        new ConnectionLimits(1000,100,100,100,3,20), port);
    try {
      pc.connect(); Thread thread = (Thread)get(pc,"connectionThread");
      // Wait longer than the old complete retry window before starting the host.
      Thread.sleep(250);
      check(thread.isAlive() && !pc.isConnected(), "phone-first wait survives old three-attempt window");
      check(!VirtualTreeManager.getInstance().isFilteringActive(), "waiting never enables focus filtering");
      try (ServerSocket late = new ServerSocket(port, 1, InetAddress.getByName("127.0.0.1"))) {
        late.setSoTimeout(2000);
        try (Socket peer = late.accept()) {
          peer.setSoTimeout(2000);
          BufferedReader input = new BufferedReader(new InputStreamReader(peer.getInputStream(), StandardCharsets.UTF_8));
          JSONObject role=new JSONObject(input.readLine());check(role.getString("type").equals("ROLE"), "late host receives fresh ROLE");
          ReadyTestSupport.acknowledge(peer,role);ReadyTestSupport.await(pc);
          check(pc.isResumeCapturePending(), "first connection retains fresh-page capture intent");
        }
      }
      thread.join(1000);
      check(!thread.isAlive() && !pc.isConnected(), "connected EOF ends cycle without reconnect");
      pc.connect(); Thread waiting = (Thread)get(pc,"connectionThread");
      Thread.sleep(60); pc.disconnect(); waiting.join(1000);
      check(!waiting.isAlive(), "explicit service off cancels preconnection waiting");
      check(get(pc,"writerExecutor") == null && get(pc,"timer") == null, "explicit stop releases executor and timer");
    } finally { pc.disconnect(); }
  }
  private static void firstByteClockAndNoProgress() throws Exception {
    for (boolean zero : new boolean[] {false, true}) {
      long[] now = {0}; int[] reads = {0};
      PcConnectionManager pc = new PcConnectionManager(() -> now[0], null, new ConnectionLimits(1000,100,100,30,1,1), 1);
      InputStream input = new InputStream() {
        public int read() { throw new AssertionError("unexpected single read"); }
        public int read(byte[] b, int offset, int count) {
          reads[0]++; now[0] += 12; b[offset] = ' ';
          if (reads[0] > 10) throw new AssertionError("frame clock incorrectly reset");
          return zero ? 0 : 1;
        }
      };
      set(pc,"reader",input); set(pc,"writer",new PrintWriter(new StringWriter())); set(pc,"isConnected",true);
      Method loop = PcConnectionManager.class.getDeclaredMethod("messageReceiveLoop"); loop.setAccessible(true); loop.invoke(pc);
      check(reads[0] == (zero ? 1 : 4), "zero-progress stops once; drip uses first-byte rather than last-byte deadline");
      check(!pc.isConnected(), "synthetic production reader closes invalid stream"); pc.disconnect();
    }
  }
  public static void main(String[] args) throws Exception {
    fixture = Files.readString(Path.of(args[0]));
    fragmentedAndCoalesced(); malformedAndEof(); writeBackpressureAndIdleStop(); finiteConnectAndLimits(); firstByteClockAndNoProgress();
    System.out.println("transport_lifecycle_checks=" + checks + " failures=0 network=LOOPBACK_ONLY native_device=NOT_RUN");
  }
}
