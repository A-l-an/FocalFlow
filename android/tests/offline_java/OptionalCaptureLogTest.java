package com.google.android.accessibility.utils;

import android.content.Context;
import android.util.Log;
import android.view.accessibility.AccessibilityNodeInfo;
import java.nio.file.*;
import java.util.Comparator;
import java.util.concurrent.CountDownLatch;

/** Real captureWork and VAT; only the optional native serializer is a fault boundary. */
public final class OptionalCaptureLogTest {
  static int checks;
  static final PcConnectionManager pc=PcConnectionManager.getInstance();
  static final VirtualTreeManager trees=VirtualTreeManager.getInstance();
  static void check(boolean value,String label){checks++;if(!value)throw new AssertionError(label);}
  static void scenario(Path root, boolean enabled) throws Exception {
    Context context=new Context(root.toFile());pc.initialize(context);
    FileLogger logger=new FileLogger(context);
    if(enabled)logger.enableLogType("ui_elements_logs");
    CaptureWorkHarness harness=new CaptureWorkHarness(logger);
    AccessibilityNodeInfoUtils.hierarchyCalls=0;
    AccessibilityNodeInfoUtils.hierarchyFailure=new IllegalStateException("SYNTHETIC_PAYLOAD_MUST_NOT_LEAK");
    Log.captured.setLength(0);
    SnapshotContext capture=pc.beginCapture();
    harness.capture(capture).run();
    check(trees.hasCapture()&&trees.isCurrent(pc.currentContext()),"valid VAT survives optional serializer failure; enabled="+enabled);
    check("synthetic".equals(trees.getVirtualTreeRoot().getString("text")),"VAT contains actual core node properties");
    check(AccessibilityNodeInfoUtils.hierarchyCalls==(enabled?1:0),"disabled optional serializer never walks nodes");
    check(!Log.captured.toString().contains("SYNTHETIC_PAYLOAD_MUST_NOT_LEAK"),"optional failure omits payload/message");
    if(enabled)check(Log.captured.toString().contains("IllegalStateException"),"enabled failure is diagnosed by class");
    check(CapturePauseTest.files(root)==0,"failed/disabled optional history writes no file");
    pc.disconnect();check(AccessibilityNodeInfo.outstandingCopies==0,"capture/native evidence released");
  }
  static void persistenceFailure(Path root) throws Exception {
    Context context=new Context(root.toFile());
    FileLogger logger=new FileLogger(context) {
      @Override public void logCapturedUiElements(SnapshotContext context, org.json.JSONObject tree) {
        throw new IllegalStateException("SYNTHETIC_PAYLOAD_MUST_NOT_LEAK");
      }
    };
    logger.enableLogType("ui_elements_logs");Log.captured.setLength(0);
    new CaptureWorkHarness(logger).capture(pc.beginCapture()).run();
    check(trees.hasCapture(),"valid VAT survives optional persistence failure");
    check(CapturePauseTest.files(root)==0,"failed optional persistence writes no file");
    check(!Log.captured.toString().contains("SYNTHETIC_PAYLOAD_MUST_NOT_LEAK"),"persistence failure omits payload/message");
    pc.disconnect();check(AccessibilityNodeInfo.outstandingCopies==0,"persistence failure releases capture handles");
  }
  static void coreFailure(Path root) throws Exception {
    Log.captured.setLength(0);
    AccessibilityNodeInfo.propertyFailure=new IllegalStateException("SYNTHETIC_CORE_PAYLOAD");
    try {
      new CaptureWorkHarness(new FileLogger(new Context(root.toFile()))).capture(pc.beginCapture()).run();
      check(!trees.hasCapture(),"invalid core must not become an accepted VAT capture");
      check(Log.captured.toString().contains("IllegalStateException"),"core error still diagnosed");
      check(!Log.captured.toString().contains("SYNTHETIC_CORE_PAYLOAD"),"core error omits payload/message");
      check(AccessibilityNodeInfo.outstandingCopies==0,"core failure releases native handles");
    } finally {AccessibilityNodeInfo.propertyFailure=null;pc.disconnect();}
  }
  public static void main(String[] args) throws Exception {
    Path root=Files.createTempDirectory("focalflow-optional-log-");
    try {
      if(args.length>0) {scenario(root,Boolean.parseBoolean(args[0]));return;}
      scenario(root,false);scenario(root,true);
      AccessibilityNodeInfoUtils.hierarchyFailure=null;
      AccessibilityNodeInfoUtils.hierarchyEntered=new CountDownLatch(1);
      AccessibilityNodeInfoUtils.hierarchyProceed=new CountDownLatch(0);
      persistenceFailure(root);coreFailure(root);
      Context context=new Context(root.toFile());FileLogger logger=new FileLogger(context);logger.enableLogType("ui_elements_logs");
      CaptureWorkHarness harness=new CaptureWorkHarness(logger);
      harness.capture(pc.beginCapture()).run();
      check(trees.hasCapture()&&CapturePauseTest.files(root)==1,"enabled healthy history and VAT both succeed");
    } finally {
      AccessibilityNodeInfoUtils.hierarchyFailure=null;pc.disconnect();
      try(java.util.stream.Stream<Path> paths=Files.walk(root)) {
        for(Path path:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator)Files.delete(path);
      }
    }
    System.out.println("optional_capture_log_checks="+checks+" failures=0 native_device=NOT_RUN");
  }
}
