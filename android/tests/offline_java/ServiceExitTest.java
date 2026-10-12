package com.google.android.accessibility.utils;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;
import org.json.JSONObject;

/** Real EOF and service callback ownership; only platform disableSelf is a sentinel. */
public final class ServiceExitTest {
  static int checks;
  static void check(boolean b,String s){checks++;if(!b)throw new AssertionError(s);}
  static Object get(Object o,String n)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
  static Method required(String name) {
    for(Method m:PcConnectionManager.class.getMethods())if(m.getName().equals(name))return m;
    throw new AssertionError("missing service exit contract: "+name);
  }
  public static void main(String[] args)throws Exception {
    Method set=required("setServiceExitFeedback"), run=required("runServiceExit");
    android.content.Context context=new android.content.Context(Files.createTempDirectory("focalflow-exit-mapping-").toFile());
    NodeMappingManager mapping=new NodeMappingManager(context);
    androidx.core.view.accessibility.AccessibilityNodeInfoCompat node=androidx.core.view.accessibility.AccessibilityNodeInfoCompat.wrap(new android.view.accessibility.AccessibilityNodeInfo());
    mapping.addMapping("synthetic-id",node);
    FocusProxy.cleanup();FocusProxy.initialize(mapping,VirtualTreeManager.getInstance());
    JSONObject source=new JSONObject(Files.readString(Path.of(args[0])));
    try(ServerSocket server=new ServerSocket(0,2,InetAddress.getByName("127.0.0.1"))){
      server.setSoTimeout(2000);
      PcConnectionManager pc=new PcConnectionManager(()->System.nanoTime()/1000000L,null,new ConnectionLimits(5000,100,500,1000,3,20),server.getLocalPort());
      List<Object> exits=Collections.synchronizedList(new ArrayList<>());
      set.invoke(pc,(Consumer<Object>)exits::add);
      try {
        pc.connect();Thread first=(Thread)get(pc,"connectionThread");
        try(Socket peer=server.accept()) {
          peer.setSoTimeout(2000);BufferedReader input=new BufferedReader(new InputStreamReader(peer.getInputStream(),StandardCharsets.UTF_8));
          JSONObject role=new JSONObject(input.readLine());check(role.getString("type").equals("ROLE"),"initial ROLE");
          ReadyTestSupport.acknowledge(peer,role);ReadyTestSupport.await(pc);
          SnapshotContext capture=pc.beginCapture();check(VirtualTreeManager.getInstance().captureVirtualTree(capture,source),"source captured");
          CompletableFuture<JSONObject> future=pc.requestUiUpdate(null);
          JSONObject request;
          do{request=new JSONObject(input.readLine());}while(!request.getString("type").equals("REQUEST_UI_UPDATE"));
          peer.getOutputStream().write((capture.message("UI_UPDATE",request.getString("requestId")).put("payload",source)+"\n").getBytes(StandardCharsets.UTF_8));peer.getOutputStream().flush();
          future.get(2,TimeUnit.SECONDS);check(VirtualTreeManager.getInstance().isFilteringActive(),"real response enables filtering");
        }
        first.join(1500);check(!first.isAlive(),"EOF does not reconnect");
        check(exits.size()==1,"EOF posts service disable exactly once");
        check(!VirtualTreeManager.getInstance().isFilteringActive() && !VirtualTreeManager.getInstance().hasCapture()
            && VirtualTreeManager.getInstance().getVirtualTreeRoot()==null,"source and filtering cleared before service exit callback");
        int[] disabled={0};Runnable disable=()->{
          check(mapping.getVirtualNodeId(node)==null,"native mapping cleared before disableSelf");
          mapping.addMapping("late-builder",node);
          check(mapping.getVirtualNodeId(node)==null,"late builder cannot recreate mappings after service exit");
          disabled[0]++;
        };
        Object old=exits.get(0);
        run.invoke(pc,old,disable);run.invoke(pc,old,disable);
        check(disabled[0]==1,"main queue consumes stop callback once");
        pc.connect();Thread second=(Thread)get(pc,"connectionThread");
        try(Socket peer=server.accept()){
          peer.setSoTimeout(2000);JSONObject role=new JSONObject(new BufferedReader(new InputStreamReader(peer.getInputStream(),StandardCharsets.UTF_8)).readLine());check(role.getString("type").equals("ROLE"),"new session opens");
          ReadyTestSupport.acknowledge(peer,role);ReadyTestSupport.await(pc);
          run.invoke(pc,old,disable);check(disabled[0]==1 && pc.isConnected(),"stale callback cannot disable new session");
          pc.pauseFiltering();second.join(1500);check(exits.size()==1,"explicit pause preserves service without stop notification");
        }
      } finally {pc.disconnect();}
    }
    NodeMappingManager offMapping=new NodeMappingManager(context);
    offMapping.addMapping("explicit-off",node);
    FocusProxy.initialize(offMapping,VirtualTreeManager.getInstance());
    PcConnectionManager stopped=new PcConnectionManager(()->0,null);
    stopped.disconnect();
    check(offMapping.getVirtualNodeId(node)==null && FocusProxy.getInstance()==null,"explicit service off releases mapping owner too");
    System.out.println("service_exit_checks="+checks+" failures=0 network=LOOPBACK_ONLY disableSelf=PLATFORM_SENTINEL");
  }
}
