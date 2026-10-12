package com.google.android.accessibility.utils;
import java.io.*;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.lang.reflect.Method;
import org.json.JSONObject;
/** Test peer consumes actual ROLE wire and sends its correlated ACK through production receipt. */
public final class ReadyTestSupport {
 public static JSONObject ack(JSONObject role){return SnapshotContext.header(role).message("SESSION_READY",role.getString("requestId"));}
 public static void receive(PcConnectionManager pc,JSONObject message)throws Exception{
  Method method=PcConnectionManager.class.getDeclaredMethod("processReceivedMessage",String.class);method.setAccessible(true);method.invoke(pc,message.toString());
 }
 public static void role(PcConnectionManager pc,StringWriter wire,Runnable flush,String user,String task)throws Exception{
  pc.sendRoleSignal(user,task);flush.run();JSONObject role=null;
  for(String line:wire.toString().split("\n"))if(!line.isEmpty()){
   JSONObject message=new JSONObject(line);if("ROLE".equals(message.optString("type")))role=message;
  }
  if(role==null)throw new AssertionError("peer did not receive actual ROLE");
  receive(pc,ack(role));if(!pc.isConnected())throw new AssertionError("matching ACK did not open production ready gate");
 }
 public static void acknowledge(Socket peer,JSONObject role)throws Exception{
  peer.getOutputStream().write((ack(role)+"\n").getBytes(StandardCharsets.UTF_8));peer.getOutputStream().flush();
 }
 public static void await(PcConnectionManager pc)throws Exception{
  long end=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(2);
  while(!pc.isConnected()&&System.nanoTime()<end)Thread.sleep(2);
  if(!pc.isConnected())throw new AssertionError("peer ACK not accepted by production reader");
 }
}
