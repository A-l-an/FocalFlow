package com.google.android.accessibility.utils;

import android.content.Context;
import java.nio.file.*;
import java.util.Comparator;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** Real captureWork/FileLogger, with a latch at the native hierarchy serialization boundary. */
public final class CapturePauseTest {
  static int checks;
  static final PcConnectionManager pc=PcConnectionManager.getInstance();
  static void check(boolean value, String label) { checks++; if (!value) throw new AssertionError(label); }
  static long files(Path root) throws Exception {
    try (java.util.stream.Stream<Path> paths=Files.walk(root)) { return paths.filter(Files::isRegularFile).count(); }
  }
  static void interruptedCapture(Path root, CaptureWorkHarness harness, Runnable interrupt, String label) throws Exception {
    AccessibilityNodeInfoUtils.hierarchyEntered=new CountDownLatch(1);
    AccessibilityNodeInfoUtils.hierarchyProceed=new CountDownLatch(1);
    android.view.accessibility.AccessibilityNodeInfo.propertyReads=0;
    long before=files(root);
    SnapshotContext capturedContext=pc.beginCapture();
    Runnable capture=harness.capture(capturedContext);
    AtomicReference<Throwable> error=new AtomicReference<>();
    Thread worker=new Thread(()->{try {capture.run();} catch (Throwable failure) {error.set(failure);}},"SyntheticHierarchyCapture");
    worker.start();
    try {
      check(AccessibilityNodeInfoUtils.hierarchyEntered.await(2,TimeUnit.SECONDS),"production capture reaches hierarchy serialization");
      interrupt.run();
      long afterInterrupt=files(root);
      AccessibilityNodeInfoUtils.hierarchyProceed.countDown();
      worker.join(2000);
      long afterWorker=files(root);
      System.out.println("capture_interrupt="+label+" paused="+pc.isFilteringPaused()+" files_before="+before
          +" files_at_interrupt_return="+afterInterrupt+" files_after_worker="+afterWorker+" worker_alive="+worker.isAlive()
          +" context_unchanged="+capturedContext.equals(pc.currentContext())
          +" native_copies="+android.view.accessibility.AccessibilityNodeInfo.outstandingCopies);
      check(!worker.isAlive() && error.get()==null,"capture finishes without native traversal failure");
      check(!VirtualTreeManager.getInstance().isCurrent(capturedContext),"interrupted capture token no longer current");
      check(android.view.accessibility.AccessibilityNodeInfo.outstandingCopies==0,"interrupted native handles released");
      check(before==afterInterrupt && afterWorker==afterInterrupt,
          "production capture wrote optional UI history after "+label+" returned");
      check(android.view.accessibility.AccessibilityNodeInfo.propertyReads==0,"invalid capture does not proceed to VAT building");
    } finally {AccessibilityNodeInfoUtils.hierarchyProceed.countDown();worker.join(2000);}
  }
  public static void main(String[] args) throws Exception {
    Path root=Files.createTempDirectory("focalflow-capture-pause-");
    try {
      Context context=new Context(root.toFile());pc.initialize(context);
      FileLogger logger=new FileLogger(context);logger.enableLogType("ui_elements_logs");
      CaptureWorkHarness harness=new CaptureWorkHarness(logger);
      interruptedCapture(root,harness,pc::pauseFiltering,"pause");
      pc.resumeFiltering();
      interruptedCapture(root,harness,pc::invalidateContext,"context invalidation");
      interruptedCapture(root,harness,pc::disconnect,"disconnect before publication");
      AccessibilityNodeInfoUtils.hierarchyEntered=new CountDownLatch(1);
      AccessibilityNodeInfoUtils.hierarchyProceed=new CountDownLatch(0);
      harness.capture(pc.beginCapture()).run();
      check(files(root)==1,"explicitly enabled current UI history still persists");
      check(!pc.isConnected(),"UI history regression uses no network connection");
    } finally {
      pc.disconnect();
      try (java.util.stream.Stream<Path> paths=Files.walk(root)) {
        for (Path path:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path);
      }
    }
    System.out.println("capture_pause_checks="+checks+" failures=0 native_tree=STUB native_device=NOT_RUN");
  }
}
