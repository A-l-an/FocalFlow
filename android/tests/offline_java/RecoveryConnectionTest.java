package com.google.android.accessibility.utils;

import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;
import com.google.android.accessibility.talkback.R;
import com.google.android.accessibility.talkback.contextmenu.FocalFlowMenuActions;

/** Queued ROLE -> pause/EOF -> new connection/ROLE -> valid production admission/application. */
public final class RecoveryConnectionTest {
  static int checks;
  static void check(boolean value, String label) { checks++; if (!value) throw new AssertionError(label); }
  static void set(PcConnectionManager pc, String name, Object value) throws Exception {
    Field f=PcConnectionManager.class.getDeclaredField(name); f.setAccessible(true); f.set(pc,value);
  }
  static Object get(PcConnectionManager pc, String name) throws Exception {
    Field f=PcConnectionManager.class.getDeclaredField(name); f.setAccessible(true); return f.get(pc);
  }
  static class QueueWriter extends AbstractExecutorService {
    final Queue<Runnable> work=new ArrayDeque<>();
    public void execute(Runnable task){ work.add(task); }
    public void shutdown(){}
    public List<Runnable> shutdownNow(){work.clear();return Collections.emptyList();}
    public boolean isShutdown(){return false;}
    public boolean isTerminated(){return false;}
    public boolean awaitTermination(long t,TimeUnit u){return true;}
    void flush(){while(!work.isEmpty())work.remove().run();}
  }
  static JSONObject read(BufferedReader reader) throws Exception {
    String line=reader.readLine(); if(line==null)throw new IOException("peer closed"); return new JSONObject(line);
  }
  public static void main(String[] args) throws Exception {
    JSONObject source=new JSONObject(Files.readString(Path.of(args[0])));
    VirtualTreeManager trees=VirtualTreeManager.getInstance();
    try(ServerSocket server=new ServerSocket(0,2,InetAddress.getByName("127.0.0.1"))){
      server.setSoTimeout(3000);
      PcConnectionManager pc=new PcConnectionManager(()->System.nanoTime()/1000000L,null,
          new ConnectionLimits(5000,500,500,5000,1,1),server.getLocalPort());
      Field singleton=PcConnectionManager.class.getDeclaredField("instance");singleton.setAccessible(true);singleton.set(null,pc);
      RecoveryCallbackHarness callback=new RecoveryCallbackHarness();
      pc.sendRoleSignal("synthetic","recovery");
      Socket firstClient=new Socket("127.0.0.1",server.getLocalPort()); Socket firstPeer=server.accept();firstPeer.setSoTimeout(2000);
      QueueWriter queue=new QueueWriter();
      set(pc,"socket",firstClient);set(pc,"reader",firstClient.getInputStream());
      set(pc,"writer",new PrintWriter(new OutputStreamWriter(firstClient.getOutputStream(),StandardCharsets.UTF_8),true));
      set(pc,"writerExecutor",queue);set(pc,"isConnected",true);
      Method start=PcConnectionManager.class.getDeclaredMethod("startSession");start.setAccessible(true);start.invoke(pc);
      String oldSession=pc.currentContext().sessionId;
      SnapshotContext oldCapture=pc.currentContext();check(!pc.isConnected() && !trees.hasCapture(),"preACK source remains empty");
      CompletableFuture<JSONObject> oldFuture=pc.requestUiUpdate(null);
      check(queue.work.size()==1,"initial ROLE genuinely queued before pause; business work blocked before ACK");
      check(FocalFlowMenuActions.handle(R.id.focalflow_filtering),"actual menu action pauses filtering");queue.flush();
      check(oldFuture.isCompletedExceptionally() && pc.isFilteringPaused(),"pause clears pending handshake while preACK business request was blocked");
      check(firstPeer.getInputStream().read()==-1,"peer sees EOF and no orphan invalidate/request before an unsent ROLE");
      firstPeer.close();
      java.util.List<PcConnectionManager.RecoveryNotice> notices = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
      pc.setRecoveryFeedback(notice -> { notices.add(notice); callback.pendingRecoveryNotice=notice; });
      check(FocalFlowMenuActions.handle(R.id.focalflow_filtering),"actual menu action requests resume");
      PcConnectionManager.RecoveryNotice resumed = notices.get(notices.size()-1);
      pc.invalidateContext(); // Ordinary window/dismiss event precedes the posted UI callback.
      check(!pc.isRecoveryNoticeCurrent(resumed) && !pc.isFilteringPaused(), "window event can invalidate announcement while resume remains enabled");
      callback.recoveryAnnouncement.run(); // Unmodified production callback body from TalkBackService.
      Socket peer=server.accept();peer.setSoTimeout(3000);
      BufferedReader incoming=new BufferedReader(new InputStreamReader(peer.getInputStream(),StandardCharsets.UTF_8));
      JSONObject role=read(incoming);ReadyTestSupport.acknowledge(peer,role);ReadyTestSupport.await(pc);
      check(callback.speechCalls==0,"stale optional notice is skipped without losing required reconnect");
      check(pc.isResumeCapturePending(), "fresh-capture intent survives new handshake and stale announcement");
      check("ROLE".equals(role.getString("type")),"resumed connection first frame is a fresh ROLE");
      check(!oldSession.equals(role.getJSONObject("context").getString("sessionId")),"resume uses a fresh connection session UUID");
      check(!FocalFlowMenuActions.isCaptureAllowed(true) && pc.isResumeCapturePending(),"menu focus transition defers capture without consuming intent");
      check(FocalFlowMenuActions.isCaptureAllowed(false),"settled menu permits fresh capture");
      SnapshotContext capture=pc.beginCapture();check(trees.captureVirtualTree(capture,source),"resumed fresh source");
      CompletableFuture<JSONObject> fresh=pc.requestUiUpdate(null);
      check(!pc.isResumeCapturePending(), "only actual current UI request consumes fresh-capture intent");
      JSONObject invalidate=read(incoming), request=read(incoming);
      check("INVALIDATE_CONTEXT".equals(invalidate.getString("type")) && "REQUEST_UI_UPDATE".equals(request.getString("type")),"ROLE then context then request wire order preserved");
      String response;
      if(args.length==3){
        Path dir=Files.createTempDirectory("focalflow-recovery-bridge-");Path input=dir.resolve("java.json"),output=dir.resolve("python.json");
        try {
          JSONObject bundle=new JSONObject().put("controls",new JSONArray().put(role).put(invalidate)).put("request",request).put("snapshot",capture.envelope(source));
          Files.writeString(input,bundle.toString());
          Process process=new ProcessBuilder(args[2],"-m","tests.protocol_bridge",input.toString(),output.toString()).directory(new File(args[1])).inheritIO().start();
          check(process.waitFor()==0,"actual resumed ROLE/control/request accepted by Python production admission");
          response=Files.readString(output);
        } finally {Files.deleteIfExists(input);Files.deleteIfExists(output);Files.deleteIfExists(dir);}
      }else response=capture.message("UI_UPDATE",request.getString("requestId")).put("payload",source).toString();
      peer.getOutputStream().write((response+"\n").getBytes(StandardCharsets.UTF_8));peer.getOutputStream().flush();
      fresh.get(2,TimeUnit.SECONDS);check(trees.isFilteringActive(),"new valid resumed result actually applies");
      JSONObject stale=oldCapture.message("UI_UPDATE","old-request").put("error","HTTP_ERROR");
      peer.getOutputStream().write((stale+"\n").getBytes(StandardCharsets.UTF_8));
      CompletableFuture<JSONObject> talk=pc.requestTalk();JSONObject talkRequest=read(incoming);
      peer.getOutputStream().write((capture.message("TALK_RESPONSE",talkRequest.getString("requestId")).put("status","NO_OP")+"\n").getBytes(StandardCharsets.UTF_8));peer.getOutputStream().flush();
      talk.get(2,TimeUnit.SECONDS);check(trees.isFilteringActive(),"old-session error processed before current no-op cannot clear resumed filtering");
      Thread thread=(Thread)get(pc,"connectionThread");pc.disconnect();pc.runPendingResume();peer.close();thread.join(2000);
      check(!thread.isAlive(),"recovery connection resources stop");
      check(get(pc,"connectionThread")==null && !pc.isConnected() && !pc.isResumeCapturePending(),"disconnect clears pending resume and capture intent");
    }
    System.out.println("recovery_connection_checks="+checks+" failures=0 network=LOOPBACK_ONLY native_device=NOT_RUN");
  }
}
