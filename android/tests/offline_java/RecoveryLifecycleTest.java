package com.google.android.accessibility.utils;

import java.io.*;
import java.lang.reflect.Field;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;

/** Deterministically orders explicit stop against the production retiring connection's restart. */
public final class RecoveryLifecycleTest {
  static int checks;
  static void check(boolean value, String label) {
    checks++;
    if (!value) throw new AssertionError(label);
  }
  static Object get(PcConnectionManager pc, String name) throws Exception {
    Field field=PcConnectionManager.class.getDeclaredField(name);
    field.setAccessible(true);return field.get(pc);
  }
  static final class RestartGate extends PcConnectionManager {
    final CountDownLatch entered=new CountDownLatch(1), proceed=new CountDownLatch(1);
    volatile Thread retiring;
    volatile boolean lifecycleLockHeld;
    RestartGate(int port) {
      super(()->System.nanoTime()/1000000L,null,new ConnectionLimits(5000,500,500,5000,1,1),port);
    }
    @Override public void connect() {
      if (Thread.currentThread()==retiring) {
        lifecycleLockHeld=Thread.holdsLock(this);
        entered.countDown();
        // This test-only gate must not let disconnect's interrupt skip the very
        // connect invocation being raced (the real invocation has no wait here).
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        boolean interrupted=false;
        while (proceed.getCount()!=0) {
          long left=deadline-System.nanoTime();
          if (left<=0) throw new AssertionError("restart gate timed out");
          try {proceed.await(left,TimeUnit.NANOSECONDS);}
          catch (InterruptedException error) {interrupted=true;}
        }
        if (interrupted) Thread.currentThread().interrupt();
      }
      super.connect();
    }
  }
  public static void main(String[] args) throws Exception {
    try (ServerSocket server=new ServerSocket(0,2,InetAddress.getByName("127.0.0.1"))) {
      server.setSoTimeout(3000);
      RestartGate pc=new RestartGate(server.getLocalPort());
      try {
        pc.pauseFiltering();pc.resumeFiltering();pc.disconnect();pc.runPendingResume();
        check(!pc.isConnected() && get(pc,"connectionThread")==null && !pc.isResumeCapturePending(),
            "stop before posted callback consumes pending resume without opening a connection");
        pc.connect();
        try (Socket peer=server.accept()) {
          peer.setSoTimeout(2000);
          BufferedReader reader=new BufferedReader(new InputStreamReader(peer.getInputStream(),StandardCharsets.UTF_8));
          org.json.JSONObject role=new org.json.JSONObject(reader.readLine());check(role.getString("type").equals("ROLE"),"initial production connection sends ROLE");
          ReadyTestSupport.acknowledge(peer,role);ReadyTestSupport.await(pc);
          synchronized (pc) {
            pc.retiring=(Thread)get(pc,"connectionThread");
            pc.pauseFiltering();pc.resumeFiltering();pc.runPendingResume();
            check((Boolean)get(pc,"connectRequested"),"resume while old reader retires queues one restart");
          }
          check(pc.entered.await(2,TimeUnit.SECONDS),"retiring reader reaches actual restart call");
          CountDownLatch stopping=new CountDownLatch(1), stopped=new CountDownLatch(1);
          Thread stop=new Thread(()->{stopping.countDown();pc.disconnect();stopped.countDown();},"ExplicitStop");
          stop.start();
          check(stopping.await(2,TimeUnit.SECONDS),"later disconnect is attempted before gated restart proceeds");
          long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
          while (stop.getState()!=Thread.State.BLOCKED && stopped.getCount()!=0 && System.nanoTime()<deadline) Thread.yield();
          check(stop.getState()==Thread.State.BLOCKED || stopped.getCount()==0,"disconnect is ordered at the lifecycle boundary");
          pc.proceed.countDown();
          stop.join(2000);pc.retiring.join(2000);
          Thread remaining=(Thread)get(pc,"connectionThread");
          if (remaining!=null) remaining.join(2000);
          check(!stop.isAlive() && stopped.getCount()==0 && !pc.retiring.isAlive(),"stop and retiring worker complete");
          check((Boolean)get(pc,"shouldStop") && !pc.isConnected() && get(pc,"connectionThread")==null,
              "stale restart must not reopen a connection after a later disconnect");
          check(pc.lifecycleLockHeld,"restart consumption and connect share the lifecycle lock");
          check(get(pc,"writerExecutor")==null && get(pc,"timer")==null && !pc.isResumeCapturePending(),
              "stop leaves no pending reconnect, capture or worker resources");
        }
      } finally {pc.proceed.countDown();pc.disconnect();}
    }
    System.out.println("recovery_lifecycle_checks="+checks+" failures=0 network=LOOPBACK_ONLY native_device=NOT_RUN");
  }
}
