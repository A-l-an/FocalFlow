package com.google.android.accessibility.utils;
import android.content.Context;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import java.lang.reflect.*;
import java.nio.file.*;
import java.io.*;
import java.util.concurrent.*;
import org.json.*;
public final class ReservationTriggerTest {
 public static void main(String[] args)throws Exception{
  Path root=Files.createTempDirectory("review-trigger-");long[] now={1000};CaptureDispatchTest.Scheduler scheduler=new CaptureDispatchTest.Scheduler(now);
  PcConnectionManager pc=new PcConnectionManager(()->now[0],scheduler);Field singleton=PcConnectionManager.class.getDeclaredField("instance");singleton.setAccessible(true);singleton.set(null,pc);
  StringWriter wire=new StringWriter();CaptureDispatchTest.WriterQueue writer=new CaptureDispatchTest.WriterQueue(),executor=new CaptureDispatchTest.WriterQueue();
  CaptureDispatchTest.set(pc,"isConnected",true);CaptureDispatchTest.set(pc,"writer",new PrintWriter(wire));CaptureDispatchTest.set(pc,"writerExecutor",writer);
    ReadyTestSupport.role(pc,wire,writer::flush,"synthetic","task");
  FileLogger logger=new FileLogger(new Context(root.toFile()));logger.initializeTransport();CaptureQueueHarness queue=new CaptureQueueHarness(logger,executor);
  queue.submit("ui_change");executor.flush();writer.flush();JSONObject first=CaptureQueueTest.lastRequest(wire);
  CaptureQueueTest.apply(pc,first,VirtualTreeManager.getInstance().getVirtualTreeRoot());executor.flush();now[0]=4000;
  queue.submit("scroll");Thread drain=new Thread(executor.tasks.remove());
  synchronized(VirtualTreeManager.getInstance()){
   drain.start();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
   while(drain.getState()!=Thread.State.BLOCKED&&System.nanoTime()<deadline)Thread.yield();
   if(drain.getState()!=Thread.State.BLOCKED)throw new AssertionError("drain did not reach reservation lock");
   System.out.println("drain_waiting_for_admission="+drain.getStackTrace()[0]);
   AccessibilityNodeInfo tapped=new AccessibilityNodeInfo();tapped.state.text="synthetic-reservation-click";
   Method submit=CaptureQueueHarness.class.getDeclaredMethod("logUIElementsToFile",String.class,AccessibilityNodeInfoCompat.class);submit.setAccessible(true);
   submit.invoke(queue,"double_tap",AccessibilityNodeInfoCompat.wrap(tapped));
  }
  drain.join(2000);writer.flush();JSONObject second=CaptureQueueTest.lastRequest(wire);
  CaptureQueueTest.apply(pc,second,VirtualTreeManager.getInstance().getVirtualTreeRoot());now[0]=8000;executor.flush();writer.flush();
  System.out.println("requests_after_all_completions="+CaptureDispatchTest.requests(wire)+" click_reached_wire="+wire.toString().contains("synthetic-reservation-click"));
  if(!wire.toString().contains("synthetic-reservation-click"))throw new AssertionError("trigger arriving during reservation discarded by ordinary capture generation advance");
  if(CaptureDispatchTest.requests(wire)!=3||queue.builds!=3)throw new AssertionError("queued click must build exactly once after reserved scroll");
  JSONObject third=CaptureQueueTest.lastRequest(wire);
  if(third.optJSONObject("interaction")==null||!"synthetic-reservation-click".equals(third.getJSONObject("interaction").getString("text")))throw new AssertionError("pending click belongs to third admitted capture");
  CaptureQueueTest.apply(pc,third,VirtualTreeManager.getInstance().getVirtualTreeRoot());executor.flush();
  if(!third.getString("requestId").equals(VirtualTreeManager.getInstance().baseRequest()))throw new AssertionError("queued click response applies");
  queue.submit("scroll");pc.disconnect();executor.flush();
  if(queue.builds!=3)throw new AssertionError("explicit disconnect drops pending capture intent");
  logger.closeTransport();
  System.out.println("reservation_trigger=PASS ordinary_snapshot_advance_preserves_pending=true response_applied=true");
 }
}
