package com.google.android.accessibility.utils;

import android.os.Handler;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Production capture/observation bodies and tree commit, with synthetic native handles and time. */
public final class ContinuityTest {
  static int checks;
  static final PcConnectionManager pc=PcConnectionManager.getInstance();
  static final VirtualTreeManager trees=VirtualTreeManager.getInstance();
  static void check(boolean value,String label){checks++;if(!value)throw new AssertionError(label);}
  static void deadlines() {
    for (String kind:new String[]{"content","scroll","mixed"}) {
      Handler.reset();List<Long> captures=new ArrayList<>();
      DelayHandler<Object> delay=new DelayHandler<Object>(){public void handle(Object arg){}};
      delay.setUiElementsLogCallback(reason->captures.add(Handler.now));
      for(int n=0;n<20;n++) {
        Handler.advance(n*500);
        if(!kind.equals("scroll"))delay.delayLogUiElementsAfterWindowChange();
        if(!kind.equals("content"))delay.delayLogUiElementsAfterScroll();
      }
      Handler.advance(10000);
      check(captures.equals(Arrays.asList(2000L,4000L,6000L,8000L,10000L)),kind+" bounded first-event deadline: "+captures);
      delay.delayLogUiElementsAfterScroll();delay.cancelAllDelayedLogging();
      Handler.advance(13000);check(captures.size()==5,"cancel removes capture");
    }
  }
  static CaptureWorkHarness capture(AccessibilityNodeInfo root) throws Exception {
    AccessibilityNodeInfoUtils.hierarchyEntered=new CountDownLatch(1);
    AccessibilityNodeInfoUtils.hierarchyProceed=new CountDownLatch(0);
    CaptureWorkHarness harness=new CaptureWorkHarness(new FileLogger(new android.content.Context(new java.io.File(System.getProperty("java.io.tmpdir")))));
    harness.root=root;
    harness.capture(pc.beginCapture()).run();
    check(trees.hasCapture(),"local capture accepted before AI result");
    return harness;
  }
  static AccessibilityEvent content(AccessibilityNodeInfo root) {
    AccessibilityEvent event=new AccessibilityEvent();event.source=root;return event;
  }
  static void duplicate() throws Exception {
    java.io.StringWriter wire=new java.io.StringWriter();
    CaptureDispatchTest.WriterQueue writer=new CaptureDispatchTest.WriterQueue();
    CaptureDispatchTest.set(pc,"isConnected",true);
    CaptureDispatchTest.set(pc,"writer",new java.io.PrintWriter(wire));
    CaptureDispatchTest.set(pc,"writerExecutor",writer);
    ReadyTestSupport.role(pc,wire,writer::flush,"synthetic","task");
    NodeMappingManager mappings=new NodeMappingManager(new android.content.Context(new java.io.File(System.getProperty("java.io.tmpdir"))));
    VirtualTreeBuilder.setMappingManager(mappings);
    AccessibilityNodeInfo root=new AccessibilityNodeInfo();root.add(new AccessibilityNodeInfo());
    CaptureWorkHarness harness=capture(root);
    SnapshotContext context=pc.currentContext();JSONObject captured=trees.getVirtualTreeRoot();
    java.lang.reflect.Field field=NodeMappingManager.class.getDeclaredField("virtualToActualNodeMap");field.setAccessible(true);
    Set<?> mappingIds=new HashSet<>(((Map<?,?>)field.get(mappings)).keySet());
    CompletableFuture<JSONObject> waiting=pc.requestUiUpdate(null);writer.flush();
    java.util.List<JSONObject> sent=CaptureDispatchTest.messages(wire);
    JSONObject request=sent.get(sent.size()-1);String requestId=request.getString("requestId");
    String before=wire.toString();
    for(int n=0;n<20;n++) {
      Handler.advance(n*100);
      AccessibilityEvent changing=content(root);
      changing.changes=AccessibilityEvent.CONTENT_CHANGE_TYPE_SUBTREE;
      root.state.text="changing-"+n;
      harness.observe(changing);
    }
    check(context.equals(pc.currentContext()),"100ms SUBTREE notifications must preserve active context");
    AccessibilityEvent description=content(root);
    description.changes=AccessibilityEvent.CONTENT_CHANGE_TYPE_CONTENT_DESCRIPTION;
    harness.observe(description);
    check(context.equals(pc.currentContext()),"unchanged description event retains capture");
    description.changes|=AccessibilityEvent.CONTENT_CHANGE_TYPE_TEXT;
    harness.observe(description);
    check(context.equals(pc.currentContext()),"unchanged combined known event retains capture");
    check(context.equals(pc.currentContext()),"duplicate content must not cancel slow current request");
    check(trees.ownsRequest(context,requestId)&&!waiting.isDone(),"slow request still owned");
    writer.flush();check(before.equals(wire.toString()),"duplicate content emits no INVALIDATE or extra request");
    check(captured.toString().equals(trees.getVirtualTreeRoot().toString()),"no UUID or raw-tree rebuild");
    check(mappingIds.equals(((Map<?,?>)field.get(mappings)).keySet()),"no native mapping mutation on duplicate notifications");
    check(harness.scheduledCaptures==0,"duplicate content must not schedule beginCapture");
    java.lang.reflect.Method receive=PcConnectionManager.class.getDeclaredMethod("processReceivedMessage",String.class);receive.setAccessible(true);
    receive.invoke(pc,context.message("UI_UPDATE",requestId).put("payload",captured).toString());
    check(waiting.isDone()&&!waiting.isCompletedExceptionally(),"latest valid result applies through production receiver");
    harness.observe(content(root));
    check(requestId.equals(trees.baseRequest()),"duplicate content retains Talk base");
    pc.requestTalk();writer.flush();sent=CaptureDispatchTest.messages(wire);
    check(requestId.equals(sent.get(sent.size()-1).getString("baseRequestId")),"Talk request still uses accepted decision base");
    VirtualTreeBuilder.setMappingManager(null);
    mappings.clearAllMappings();
    pc.disconnect();
  }
  static void changes() throws Exception {
    for(String mutation:new String[]{"text","description","class","view-id","clickable","checkable","checked","focusable","enabled","password","selected","left","top","right","bottom","null-text","null-description","null-class","null-view-id","visible","scrollable","window","package","remove","replace","reorder","unknown","subtree","missing","scroll","window-event"}) {
      AccessibilityNodeInfo root=new AccessibilityNodeInfo(),a=new AccessibilityNodeInfo(),b=new AccessibilityNodeInfo();root.add(a);root.add(b);
      CaptureWorkHarness harness=capture(root);SnapshotContext context=pc.currentContext();JSONObject result=trees.getVirtualTreeRoot();
      trees.registerRequest(context,"stale",false);AccessibilityEvent event=content(root);
      switch(mutation) {
        case "text":a.state.text="changed";break;
        case "description":a.state.description="changed";break;
        case "class":a.state.className="android.widget.Button";break;
        case "view-id":a.state.viewId="synthetic:other";break;
        case "clickable":a.state.clickable=false;break;
        case "checkable":a.state.checkable=true;break;
        case "focusable":a.state.focusable=false;break;
        case "enabled":a.state.enabled=false;break;
        case "password":a.state.password=true;break;
        case "selected":a.state.selected=true;break;
        case "left":a.state.left=1;break;
        case "top":a.state.top=1;break;
        case "right":a.state.right=11;break;
        case "bottom":a.state.bottom=11;break;
        case "null-text":a.state.text=null;break;
        case "null-description":a.state.description=null;break;
        case "null-class":a.state.className=null;break;
        case "null-view-id":a.state.viewId=null;break;
        case "checked":a.state.checked=true;break;
        case "visible":a.state.visible=false;break;
        case "scrollable":a.state.scrollable=true;break;
        case "window":a.state.windowId=2;break;
        case "package":a.state.packageName="changed.app";break;
        case "remove":root.state.children.remove(a);a.state.valid=false;event.source=a;break;
        case "replace":root.state.children.set(0,new AccessibilityNodeInfo());break;
        case "reorder":Collections.reverse(root.state.children);break;
        case "unknown":event.changes=0;break;
        case "subtree":event.changes=AccessibilityEvent.CONTENT_CHANGE_TYPE_SUBTREE;break;
        case "missing":event.source=null;break;
        case "scroll":event.type=AccessibilityEvent.TYPE_VIEW_SCROLLED;break;
        case "window-event":event.type=AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED;event.packageName="com.android.launcher";break;
      }
      harness.observe(event);
      check(context.equals(pc.currentContext()),mutation+" preserves admitted capture");
      check(trees.applyFilteredVirtualTree(context,"stale",result),mutation+" permits captured response");
    }
  }
  static void largePage() throws Exception {
    AccessibilityNodeInfo root=new AccessibilityNodeInfo();
    for(int n=0;n<100;n++)root.add(new AccessibilityNodeInfo());
    CaptureWorkHarness harness=capture(root);SnapshotContext context=pc.currentContext();
    trees.registerRequest(context,"large-page",false);
    harness.observe(content(root.state.children.get(70)));
    check(trees.ownsRequest(context,"large-page"),"small source on >64-node page retains slow request");
    harness.observe(content(root));
    check(context.equals(pc.currentContext()),"large content notifications do not inspect or invalidate capture");
  }
  static void atomicObservation() throws Exception {
    AccessibilityNodeInfo root=new AccessibilityNodeInfo();CaptureWorkHarness harness=capture(root);
    SnapshotContext context=pc.currentContext();JSONObject candidate=trees.getVirtualTreeRoot();
    trees.registerRequest(context,"racing",false);
    AccessibilityNodeInfo.onRefresh=()->{throw new AssertionError("content notification must not read native nodes");};
    try {
      root.state.text="changed during inference";harness.observe(content(root));
      check(trees.applyFilteredVirtualTree(context,"racing",candidate),"content event cannot reject completed response");
    } finally {AccessibilityNodeInfo.onRefresh=null;}
  }
  static androidx.core.view.accessibility.AccessibilityNodeInfoCompat action(String text) {
    androidx.core.view.accessibility.AccessibilityNodeInfoCompat node=new androidx.core.view.accessibility.AccessibilityNodeInfoCompat(text);
    node.text=text;return node;
  }
  static void gestures() {
    Handler.reset();UiDelayHarness harness=new UiDelayHarness();
    androidx.core.view.accessibility.AccessibilityNodeInfoCompat first=action("accepted tap");
    harness.schedule(first);
    Handler.advance(1000);harness.renewPriority();
    harness.uiLoggingDelayHandler.delayLogUiElementsAfterWindowChange();
    harness.uiLoggingDelayHandler.delayLogUiElementsAfterScroll();
    Handler.advance(2999);check(harness.captures.isEmpty(),"tap retains three-second wait");
    Handler.advance(3000);check(harness.captures.equals(Arrays.asList("accepted tap")),"generic priority timer must not swallow interaction capture");
    check(first.recycles==1,"executed tap node released exactly once");
    Handler.advance(6000);check(!harness.doubleTapTriggered,"independent priority-reset callback runs");
    androidx.core.view.accessibility.AccessibilityNodeInfoCompat second=action("second");
    harness.schedule(second);harness.schedule(null);Handler.advance(9000);
    check(harness.captures.equals(Arrays.asList("accepted tap","second")),"duplicate null trigger preserves saved action");
    check(second.recycles==1,"duplicate trigger does not leak saved action");
    androidx.core.view.accessibility.AccessibilityNodeInfoCompat replaced=action("replaced"),last=action("last");
    harness.schedule(replaced);harness.schedule(last);
    check(replaced.recycles==1,"replaced node released");
    harness.uiLoggingDelayHandler.removeMessages();Handler.advance(15000);
    check(last.recycles==1&&harness.captures.size()==2,"service stop clears capture and releases node");
  }
  static void resourcesAndReadFailures() throws Exception {
    AccessibilityNodeInfo root=new AccessibilityNodeInfo();root.add(new AccessibilityNodeInfo());
    CaptureWorkHarness harness=capture(root);int held=AccessibilityNodeInfo.outstandingCopies;
    for(int n=0;n<10;n++)harness.observe(content(root.state.children.get(0)));
    check(held==AccessibilityNodeInfo.outstandingCopies,"comparison recycles all temporary native handles");
    for(String failure:new String[]{"exception","time"}) {
      harness=capture(root);SnapshotContext context=pc.currentContext();
      AccessibilityNodeInfo.onRefresh=()->{if(failure.equals("exception"))throw new IllegalStateException("synthetic native failure");else Handler.now+=13;};
      try {harness.observe(content(root));}finally {AccessibilityNodeInfo.onRefresh=null;}
      check(context.equals(pc.currentContext()),failure+" event does not read or invalidate capture");
      check(AccessibilityNodeInfo.outstandingCopies==held,failure+" event does not change native ownership");
    }
    capture(root);pc.disconnect();
    check(!trees.hasCapture()&&AccessibilityNodeInfo.outstandingCopies==0,"disconnect clears evidence even before a connection exists");
  }
  public static void main(String[] args) throws Exception {
    if(args.length>0&&args[0].equals("delay"))deadlines();
    else if(args.length>0&&args[0].equals("gestures"))gestures();
    else {duplicate();changes();largePage();atomicObservation();resourcesAndReadFailures();}
    pc.disconnect();
    System.out.println("continuity_checks="+checks+" failures=0 native_device=NOT_RUN");
  }
}
