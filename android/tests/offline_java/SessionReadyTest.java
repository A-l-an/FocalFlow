package com.google.android.accessibility.utils;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.JSONObject;
/** Real loopback startup/READY/EOF transitions; native disable is a callback sentinel. */
public final class SessionReadyTest {
 static int checks;
 static void check(boolean value,String label){checks++;if(!value)throw new AssertionError(label);}
 static Object get(PcConnectionManager pc,String name)throws Exception{Field f=PcConnectionManager.class.getDeclaredField(name);f.setAccessible(true);return f.get(pc);}
 static PcConnectionManager manager(int port,int handshake)throws Exception{
  PcConnectionManager pc=new PcConnectionManager(()->System.nanoTime()/1000000L,null,new ConnectionLimits(5000,handshake,500,1000,3,20),port);
  pc.initialize(new android.content.Context(Files.createTempDirectory("focalflow-ready-").toFile()));return pc;
 }
 static JSONObject read(Socket peer)throws Exception{
  peer.setSoTimeout(2000);ByteArrayOutputStream bytes=new ByteArrayOutputStream();int value;
  while((value=peer.getInputStream().read())!=-1 && value!='\n')bytes.write(value);
  if(value==-1)throw new AssertionError("missing frame");return new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));
 }
 static JSONObject ack(JSONObject role){return SnapshotContext.header(role).message("SESSION_READY",role.getString("requestId"));}
 static void send(Socket peer,JSONObject message)throws Exception{peer.getOutputStream().write((message+"\n").getBytes(StandardCharsets.UTF_8));peer.getOutputStream().flush();}
 static void waitReady(PcConnectionManager pc)throws Exception{long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);while(!pc.isConnected()&&System.nanoTime()<end)Thread.sleep(5);check(pc.isConnected(),"valid matching ACK establishes readiness");}
 static void initialBridgeEof(String[] args)throws Exception{
  try(ServerSocket server=new ServerSocket(0,3,InetAddress.getByName("127.0.0.1"))){
   server.setSoTimeout(2000);PcConnectionManager pc=manager(server.getLocalPort(),3000);
   List<PcConnectionManager.ServiceExitNotice> exits=Collections.synchronizedList(new ArrayList<>());
   List<PcConnectionManager.RecoveryState> notices=Collections.synchronizedList(new ArrayList<>());
   pc.setServiceExitFeedback(exits::add);pc.setRecoveryFeedback(n->notices.add(n.state));
   Thread worker=null;
   try{
    pc.connect();worker=(Thread)get(pc,"connectionThread");
    try(Socket bridge=server.accept()){
     read(bridge);Thread.sleep(30);
     check(!pc.isConnected(),"USB bridge TCP accept alone must not expose backend ready");
     check(!notices.contains(PcConnectionManager.RecoveryState.CONNECTED),"no connected notice before ACK");
    }
    try(Socket bridge=server.accept()){read(bridge);}
    check(exits.isEmpty() && worker.isAlive(),"preACK bridge EOF keeps service and initial wait alive");
    try(Socket backend=server.accept()){
     JSONObject role=read(backend);JSONObject ready=ack(role);
     if(args.length==3){
      Path folder=Files.createTempDirectory("focalflow-ready-bridge-");Path input=folder.resolve("role.json"),output=folder.resolve("ready.json");
      try{Files.writeString(input,role.toString());Process child=new ProcessBuilder(args[2],"-B","-m","tests.session_ready_bridge",input.toString(),output.toString()).directory(new File(args[1])).inheritIO().start();check(child.waitFor()==0,"real Python backend produces Java ROLE ACK without model calls");ready=new JSONObject(Files.readString(output));}
      finally{Files.deleteIfExists(input);Files.deleteIfExists(output);Files.deleteIfExists(folder);}
     }
     send(backend,ready);waitReady(pc);
     check(pc.isResumeCapturePending(),"first valid ACK preserves fresh capture intent");
     send(backend,ack(role));Thread.sleep(30);
     check(Collections.frequency(notices,PcConnectionManager.RecoveryState.CONNECTED)==1,"duplicate ACK cannot repeat connected capture notice");
    }
    worker.join(1000);check(!worker.isAlive() && exits.size()==1,"postACK EOF stops service exactly once");
   }finally{pc.disconnect();if(worker!=null)worker.join(1000);}
  }
 }
 static void newTaskRequiresFreshCapture(String fixture)throws Exception {
  try(ServerSocket server=new ServerSocket(0,2,InetAddress.getByName("127.0.0.1"))){
   PcConnectionManager pc=manager(server.getLocalPort(),700);Thread worker=null;
   try{pc.connect();worker=(Thread)get(pc,"connectionThread");try(Socket peer=server.accept()){
    JSONObject first=read(peer);send(peer,ack(first));waitReady(pc);
    JSONObject tree=new JSONObject(Files.readString(Path.of(fixture)));
    SnapshotContext capture=pc.beginCapture();check(VirtualTreeManager.getInstance().captureVirtualTree(capture,tree),"capture after valid ACK");
    CompletableFuture<JSONObject> future=pc.requestUiUpdate(null);JSONObject request;
    do{request=read(peer);}while(!"REQUEST_UI_UPDATE".equals(request.getString("type")));
    send(peer,capture.message("UI_UPDATE",request.getString("requestId")).put("payload",tree));future.get(2,TimeUnit.SECONDS);
    check(!pc.isResumeCapturePending(),"first UI request consumed capture intent");
    pc.sendRoleSignal("synthetic","next");JSONObject next=read(peer);
    check(!pc.isConnected(),"new task revokes current ready");
    send(peer,ack(first));Thread.sleep(30);check(!pc.isConnected(),"old task ACK cannot resume new task");
    send(peer,ack(next));waitReady(pc);check(pc.isResumeCapturePending(),"new task valid ACK restores fresh-capture intent");
   }}finally{pc.disconnect();if(worker!=null)worker.join(1000);}
  }
 }
 public static void main(String[] args)throws Exception{
  initialBridgeEof(args);newTaskRequiresFreshCapture(args[0]);System.out.println("session_ready_checks="+checks+" failures=0 network=LOOPBACK_ONLY disableSelf=CALLBACK_SENTINEL");
 }
}
