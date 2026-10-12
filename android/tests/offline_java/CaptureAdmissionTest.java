package com.google.android.accessibility.utils;
import android.content.Context;
import java.lang.reflect.*;
import java.nio.file.*;
import java.io.*;
import java.util.concurrent.*;
import org.json.*;
public final class CaptureAdmissionTest {
 public static void main(String[] args) throws Exception {
  Path root=Files.createTempDirectory("review-admission-");
  long[] now={1000}; CaptureDispatchTest.Scheduler scheduler=new CaptureDispatchTest.Scheduler(now);
  PcConnectionManager pc=new PcConnectionManager(()->now[0],scheduler);
  Field singleton=PcConnectionManager.class.getDeclaredField("instance");singleton.setAccessible(true);singleton.set(null,pc);
  StringWriter wire=new StringWriter();CaptureDispatchTest.WriterQueue writer=new CaptureDispatchTest.WriterQueue(),executor=new CaptureDispatchTest.WriterQueue();
  CaptureDispatchTest.set(pc,"isConnected",true);CaptureDispatchTest.set(pc,"writer",new PrintWriter(wire));CaptureDispatchTest.set(pc,"writerExecutor",writer);
    ReadyTestSupport.role(pc,wire,writer::flush,"synthetic","task");
  FileLogger logger=new FileLogger(new Context(root.toFile()));logger.initializeTransport();
  CaptureQueueHarness queue=new CaptureQueueHarness(logger,executor);
  queue.submit("ui_change");executor.flush();writer.flush();
  JSONObject initial=CaptureQueueTest.lastRequest(wire);
  CaptureQueueTest.apply(pc,initial,VirtualTreeManager.getInstance().getVirtualTreeRoot());executor.flush();
  if(VirtualTreeManager.getInstance().baseRequest()==null)throw new AssertionError("initial classification absent");
  now[0]=4000;queue.submit("scroll");
  Field lockField=CaptureQueueHarness.class.getDeclaredField("captureQueueLock");lockField.setAccessible(true);Object lock=lockField.get(queue);
  Thread drain=new Thread(executor.tasks.remove());CompletableFuture<JSONObject> talk;
  synchronized(lock) {
   drain.start();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
   while(drain.getState()!=Thread.State.BLOCKED&&System.nanoTime()<deadline)Thread.yield();
   if(drain.getState()!=Thread.State.BLOCKED)throw new AssertionError("drain did not reach queue lock");
   System.out.println("drain_waiting_for_queue_admission="+drain.getStackTrace()[0]);
   talk=pc.requestTalk();writer.flush();
   if(talk.isDone())throw new AssertionError("Talk not admitted");
   System.out.println("talk_admitted=true pending_before_release=true");
  }
  drain.join(2000);writer.flush();
  System.out.println("talk_cancelled_by_ordinary_capture="+talk.isCompletedExceptionally()+" builds="+queue.builds);
  if(talk.isCompletedExceptionally()) {
   try{talk.join();}catch(CompletionException e){System.out.println("reason="+e.getCause().getMessage());}
   throw new AssertionError("ordinary capture must wait for concurrently admitted Talk");
  }
  if(queue.builds!=1)throw new AssertionError("waiting scroll must not build over Talk");
  JSONObject talkRequest=CaptureDispatchTest.messages(wire).get(CaptureDispatchTest.messages(wire).size()-1);
  if(!"REQUEST_TALK".equals(talkRequest.getString("type")))throw new AssertionError("Talk owns wire before successor");
  Method receive=PcConnectionManager.class.getDeclaredMethod("processReceivedMessage",String.class);receive.setAccessible(true);
  receive.invoke(pc,SnapshotContext.header(talkRequest).message("TALK_RESPONSE",talkRequest.getString("requestId")).put("status","NO_OP").toString());
  if(!talk.isDone()||talk.isCompletedExceptionally())throw new AssertionError("admitted Talk must complete successfully");
  executor.flush();writer.flush();
  if(queue.builds!=2||CaptureDispatchTest.requests(wire)!=2)throw new AssertionError("retained scroll must run once after Talk completion");
  JSONObject successor=CaptureQueueTest.lastRequest(wire);
  CaptureQueueTest.apply(pc,successor,VirtualTreeManager.getInstance().getVirtualTreeRoot());executor.flush();
  if(!successor.getString("requestId").equals(VirtualTreeManager.getInstance().baseRequest()))throw new AssertionError("scroll response must apply");
  pc.disconnect();logger.closeTransport();
  System.out.println("capture_admission_race=PASS talk_preserved=true pending_scroll_built=true successor_applied=true native_device=NOT_RUN");
 }
}
