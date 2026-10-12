package com.google.android.accessibility.utils;
import android.content.Context;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import java.lang.reflect.*;
import java.nio.file.*;
import java.io.*;
import org.json.*;
/** Real queue and request payload; stub copy recycling is checked on each actual queued handle. */
public final class InteractionCoalescingTest {
 public static void main(String[] args)throws Exception {
  Path root=Files.createTempDirectory("capture-interaction-");long[] now={1000};CaptureDispatchTest.Scheduler scheduler=new CaptureDispatchTest.Scheduler(now);
  PcConnectionManager pc=new PcConnectionManager(()->now[0],scheduler);Field singleton=PcConnectionManager.class.getDeclaredField("instance");singleton.setAccessible(true);singleton.set(null,pc);
  StringWriter wire=new StringWriter();CaptureDispatchTest.WriterQueue writer=new CaptureDispatchTest.WriterQueue(),executor=new CaptureDispatchTest.WriterQueue();
  CaptureDispatchTest.set(pc,"isConnected",true);CaptureDispatchTest.set(pc,"writer",new PrintWriter(wire));CaptureDispatchTest.set(pc,"writerExecutor",writer);
    ReadyTestSupport.role(pc,wire,writer::flush,"synthetic","task");
  FileLogger logger=new FileLogger(new Context(root.toFile()));logger.initializeTransport();CaptureQueueHarness queue=new CaptureQueueHarness(logger,executor);
  Method submit=CaptureQueueHarness.class.getDeclaredMethod("logUIElementsToFile",String.class,AccessibilityNodeInfoCompat.class);submit.setAccessible(true);
  AccessibilityNodeInfo solo=new AccessibilityNodeInfo();solo.state.text="solo-choice";
  submit.invoke(queue,"double_tap",AccessibilityNodeInfoCompat.wrap(solo));executor.flush();writer.flush();JSONObject a=CaptureQueueTest.lastRequest(wire);
  if(a.optJSONObject("interaction")==null||!"solo-choice".equals(a.getJSONObject("interaction").getString("text")))throw new AssertionError("solo tap positive control must carry its text");
  System.out.println("interaction_solo_tap_positive_control=PASS");
  Field pending=CaptureQueueHarness.class.getDeclaredField("pendingCaptureNode");pending.setAccessible(true);
  AccessibilityNodeInfo tapped=new AccessibilityNodeInfo();tapped.state.text="first-choice";
  submit.invoke(queue,"double_tap",AccessibilityNodeInfoCompat.wrap(tapped));
  AccessibilityNodeInfoCompat first=(AccessibilityNodeInfoCompat)pending.get(queue);
  if(first==null||first.recycles!=0)throw new AssertionError("pending tap owns its copied handle");
  AccessibilityNodeInfo latest=new AccessibilityNodeInfo();latest.state.text="latest-choice";
  submit.invoke(queue,"double_tap",AccessibilityNodeInfoCompat.wrap(latest));
  AccessibilityNodeInfoCompat second=(AccessibilityNodeInfoCompat)pending.get(queue);
  if(second==first||first.recycles!=1||second.recycles!=0)throw new AssertionError("new nonnull tap replaces and recycles previous copy once");
  queue.submit("scroll");queue.submit("ui_change");
  if(pending.get(queue)!=second||second.recycles!=0)throw new AssertionError("null trigger must retain latest meaningful tap");
  CaptureQueueTest.apply(pc,a,VirtualTreeManager.getInstance().getVirtualTreeRoot());now[0]=5000;executor.flush();writer.flush();
  JSONObject b=CaptureQueueTest.lastRequest(wire);
  if(CaptureDispatchTest.requests(wire)!=2||queue.builds!=2)throw new AssertionError("one latest successor only");
  if(b.optJSONObject("interaction")==null||!"latest-choice".equals(b.getJSONObject("interaction").getString("text")))throw new AssertionError("null scroll/window trigger erased latest tap payload");
  if(second.recycles!=1)throw new AssertionError("accepted tap copy released exactly once");
  submit.invoke(queue,"double_tap",AccessibilityNodeInfoCompat.wrap(latest));
  AccessibilityNodeInfoCompat oldTask=(AccessibilityNodeInfoCompat)pending.get(queue);
  ReadyTestSupport.role(pc,wire,writer::flush,"synthetic","reset");now[0]=8000;queue.submit("ui_change");executor.flush();writer.flush();
  if(CaptureQueueTest.lastRequest(wire).optJSONObject("interaction")!=null)throw new AssertionError("old task interaction must not cross boundary");
  if(oldTask.recycles!=1)throw new AssertionError("old task copy released exactly once");
  pc.disconnect();logger.closeTransport();
  System.out.println("interaction_coalescing=PASS latest_nonnull_retained=true replacement_recycled=true task_boundary_cleared=true native_device=NOT_RUN");
 }
}
