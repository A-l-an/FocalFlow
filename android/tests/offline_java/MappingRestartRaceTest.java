package com.google.android.accessibility.utils;
import android.content.Context;
import android.view.accessibility.AccessibilityNodeInfo;
import java.util.concurrent.*;
import java.lang.reflect.*;
import org.json.JSONObject;
public final class MappingRestartRaceTest {
 static int count(NodeMappingManager m)throws Exception{Field f=NodeMappingManager.class.getDeclaredField("virtualToActualNodeMap");f.setAccessible(true);return ((java.util.Map<?,?>)f.get(m)).size();}
 static final class BlockedRoot extends AccessibilityNodeInfo {
  final CountDownLatch entered=new CountDownLatch(1), proceed=new CountDownLatch(1);
  @Override public CharSequence getClassName(){entered.countDown();try{if(!proceed.await(3,TimeUnit.SECONDS))throw new AssertionError("gate");}catch(InterruptedException e){throw new AssertionError(e);}return super.getClassName();}
 }
 static void admittedWorkKeepsOwner(Context ctx)throws Exception {
  long[] now={1000};CaptureDispatchTest.Scheduler scheduler=new CaptureDispatchTest.Scheduler(now);
  PcConnectionManager pc=new PcConnectionManager(()->now[0],scheduler);
  Field singleton=PcConnectionManager.class.getDeclaredField("instance");singleton.setAccessible(true);singleton.set(null,pc);
  java.io.StringWriter wire=new java.io.StringWriter();CaptureDispatchTest.WriterQueue writer=new CaptureDispatchTest.WriterQueue(),executor=new CaptureDispatchTest.WriterQueue();
  CaptureDispatchTest.set(pc,"isConnected",true);CaptureDispatchTest.set(pc,"writer",new java.io.PrintWriter(wire));CaptureDispatchTest.set(pc,"writerExecutor",writer);
    ReadyTestSupport.role(pc,wire,writer::flush,"synthetic","task");
  FileLogger logger=new FileLogger(ctx);logger.initializeTransport();
  CaptureQueueHarness queue=new CaptureQueueHarness(logger,executor);
  NodeMappingManager admitted=new NodeMappingManager(ctx), replacement=new NodeMappingManager(ctx);
  queue.focalFlowMappingManager=admitted;VirtualTreeBuilder.setMappingManager(admitted);
  queue.submit("ui_change");
  // The admission already captured an owner; execution has not entered the builder.
  admitted.close();queue.focalFlowMappingManager=replacement;VirtualTreeBuilder.setMappingManager(replacement);
  executor.flush();writer.flush();
  int after=count(replacement);
  if(count(admitted)!=0 || after!=0)throw new AssertionError("admitted old capture adopted new mapping owner at late builder entry");
  VirtualTreeBuilder.buildVirtualTree(new AccessibilityNodeInfo(),null,replacement);
  if(count(replacement)!=1)throw new AssertionError("new service's own capture did not populate its mapping owner");
  System.out.println("mapping_restart_admission=PASS old_mapping_count="+count(admitted)+" new_after_retired_admission="+after+" new_after_own_capture="+count(replacement));
  pc.disconnect();admitted.close();replacement.close();logger.closeTransport();
 }
 public static void main(String[] args)throws Exception{
  Context ctx=new Context(new java.io.File(args[0]));
  NodeMappingManager oldMap=new NodeMappingManager(ctx);
  FocusProxy.cleanup();FocusProxy.initialize(oldMap,VirtualTreeManager.getInstance());VirtualTreeBuilder.setMappingManager(oldMap);
  BlockedRoot root=new BlockedRoot();AccessibilityNodeInfo oldChild=new AccessibilityNodeInfo();oldChild.state.text="previous-service-node";root.add(oldChild);
  Thread retired=new Thread(()->VirtualTreeBuilder.buildVirtualTree(root));retired.start();
  if(!root.entered.await(3,TimeUnit.SECONDS))throw new AssertionError("builder not admitted");
  FocusProxy.cleanup();
  NodeMappingManager newMap=new NodeMappingManager(ctx);
  VirtualTreeBuilder.setMappingManager(newMap);FocusProxy.initialize(newMap,VirtualTreeManager.getInstance());
  int before=count(newMap);root.proceed.countDown();retired.join(3000);if(retired.isAlive())throw new AssertionError("builder blocked");
  System.out.println("old_mapping_count="+count(oldMap)+" new_mapping_before="+before+" new_mapping_after_retired_worker="+count(newMap)+" new_service_capture_count=0 synthetic_platform=true");
  if(count(oldMap)!=0 || count(newMap)!=0)throw new AssertionError("retired builder repopulated a new service mapping owner");
  FocusProxy.cleanup();
  System.out.println("mapping_restart_mid_recursion=PASS synthetic_platform=true");
  admittedWorkKeepsOwner(ctx);
 }
}
