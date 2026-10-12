package com.google.android.accessibility.utils;

import android.content.Context;
import android.os.Handler;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.lang.reflect.*;
import java.nio.file.*;
import java.io.*;
import org.json.*;
import java.util.concurrent.*;

/** Exact service admission/drain + builder/store/receiver, synthetic native handles and manual time. */
public final class CaptureQueueTest {
  static int checks;
  static void check(boolean value,String label){checks++;if(!value)throw new AssertionError(label);}
  static JSONObject lastRequest(StringWriter wire) {
    java.util.List<JSONObject> messages=CaptureDispatchTest.messages(wire);
    for(int i=messages.size()-1;i>=0;i--) if("REQUEST_UI_UPDATE".equals(messages.get(i).getString("type"))) return messages.get(i);
    throw new AssertionError("no UI request");
  }
  static void apply(PcConnectionManager pc,JSONObject request,JSONObject captured) throws Exception {
    Method receive=PcConnectionManager.class.getDeclaredMethod("processReceivedMessage",String.class);receive.setAccessible(true);
    receive.invoke(pc,SnapshotContext.header(request).message("UI_UPDATE",request.getString("requestId")).put("payload",captured).toString());
  }
  public static void main(String[] args) throws Exception {
    Path root=Files.createTempDirectory("focalflow-queue-");
    long[] now={1000};CaptureDispatchTest.Scheduler scheduler=new CaptureDispatchTest.Scheduler(now);
    PcConnectionManager pc=new PcConnectionManager(()->now[0],scheduler);
    Field singleton=PcConnectionManager.class.getDeclaredField("instance");singleton.setAccessible(true);singleton.set(null,pc);
    StringWriter wire=new StringWriter();CaptureDispatchTest.WriterQueue writer=new CaptureDispatchTest.WriterQueue();
    CaptureDispatchTest.WriterQueue executor=new CaptureDispatchTest.WriterQueue();
    CaptureDispatchTest.set(pc,"isConnected",true);CaptureDispatchTest.set(pc,"writer",new PrintWriter(wire));CaptureDispatchTest.set(pc,"writerExecutor",writer);
    ReadyTestSupport.role(pc,wire,writer::flush,"synthetic","task");
    Context context=new Context(root.toFile());FileLogger logger=new FileLogger(context);logger.initializeTransport();
    CaptureQueueHarness queue=new CaptureQueueHarness(logger,executor);
    CaptureWorkHarness observer=new CaptureWorkHarness(logger);
    CaptureDispatchTest.set(pc,"isConnected",false);
    queue.submit("ui_change");executor.flush();
    check(queue.builds==0 && !VirtualTreeManager.getInstance().hasCapture(),"phone-first waiting ignores capture work and keeps source empty");
    CaptureDispatchTest.set(pc,"isConnected",true);
    CaptureDispatchTest.set(pc,"captureAfterConnect",true);
    queue.root.state.packageName="com.android.settings";
    queue.submit("resume");executor.flush();writer.flush();
    check(!VirtualTreeManager.getInstance().hasCapture() && pc.isResumeCapturePending(),"first connection waits until accessibility settings are left before capture");
    queue.root.state.packageName="synthetic.app";queue.builds=0;
    AccessibilityNodeInfoUtils.hierarchyEntered=new CountDownLatch(1);AccessibilityNodeInfoUtils.hierarchyProceed=new CountDownLatch(1);
    logger.enableLogType("ui_elements_logs");
    queue.submit("ui_change");
    Runnable first=executor.tasks.remove();Thread build=new Thread(first);build.start();
    check(AccessibilityNodeInfoUtils.hierarchyEntered.await(2,TimeUnit.SECONDS),"build reaches native hierarchy boundary");
    SnapshotContext admitted=pc.currentContext();
    for(int n=0;n<20;n++) {
      Handler.advance(n*100);AccessibilityEvent event=new AccessibilityEvent();event.changes=AccessibilityEvent.CONTENT_CHANGE_TYPE_SUBTREE;event.source=queue.root;
      queue.root.state.text="changing-"+n;observer.observe(event);
    }
    queue.submit("scroll");queue.submit("double_tap");
    check(admitted.equals(pc.currentContext()),"100ms SUBTREE and busy triggers cannot invalidate builder");
    AccessibilityNodeInfoUtils.hierarchyProceed.countDown();build.join(2000);writer.flush();
    check(!build.isAlive()&&queue.builds==1,"only A built while its response is pending");
    JSONObject a=lastRequest(wire),captured=VirtualTreeManager.getInstance().getVirtualTreeRoot();
    byte[] slot=Files.readAllBytes(root.resolve("screen_reader_logs/virtual_tree_logs/User_transport/Task_transport/virtual_tree_current.json"));
    queue.submit("ui_change");queue.submit("scroll");executor.flush();writer.flush();
    check(queue.builds==1&&CaptureDispatchTest.requests(wire)==1,"busy window/scroll/double-tap retained without a new build/request");
    check(java.util.Arrays.equals(slot,Files.readAllBytes(root.resolve("screen_reader_logs/virtual_tree_logs/User_transport/Task_transport/virtual_tree_current.json"))),"transport slot remains A during inference");
    for(int n=20;n<40;n++){Handler.advance(n*100);AccessibilityEvent event=new AccessibilityEvent();event.changes=AccessibilityEvent.CONTENT_CHANGE_TYPE_SUBTREE;observer.observe(event);}
    apply(pc,a,captured);
    check(a.getString("requestId").equals(VirtualTreeManager.getInstance().baseRequest()),"A applies despite sustained notifications");
    now[0]=4000;executor.flush();writer.flush();
    check(queue.builds==2&&CaptureDispatchTest.requests(wire)==2,"exactly latest pending trigger runs after A applies");
    JSONObject b=lastRequest(wire);JSONObject next=VirtualTreeManager.getInstance().getVirtualTreeRoot();
    queue.submit("double_tap");pc.pauseFiltering();executor.flush();writer.flush();
    check(queue.builds==2&&pc.isFilteringPaused(),"explicit pause cancels active chain and drops queued work");
    apply(pc,b,next);check(!VirtualTreeManager.getInstance().hasCapture(),"late response after pause cannot restore capture");
    pc.disconnect();logger.closeTransport();
    System.out.println("capture_queue_checks="+checks+" failures=0 content_interval_ms=100 native_device=NOT_RUN");
  }
}
