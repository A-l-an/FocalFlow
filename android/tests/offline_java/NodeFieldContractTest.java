package com.google.android.accessibility.utils;

import android.view.accessibility.AccessibilityNodeInfo;
import java.lang.reflect.Method;
import java.util.*;
import org.json.JSONObject;

/** Independent wire key/type/value/null contract against both actual production writers. */
public final class NodeFieldContractTest {
  static int checks;
  static void check(boolean value, String label) {checks++; if(!value)throw new AssertionError(label);}
  static final String EXPECTED="{\"className\":\"android.widget.Button\",\"text\":\"synthetic item\",\"contentDescription\":\"synthetic detail\",\"viewIdResourceName\":\"synthetic:id/item\",\"isClickable\":true,\"isCheckable\":true,\"isChecked\":false,\"isFocusable\":false,\"isEnabled\":true,\"isPassword\":false,\"isSelected\":true,\"centerCoordinates\":\"8,16\",\"bounds\":{\"left\":2,\"top\":6,\"right\":14,\"bottom\":26}}";
  static void properties(JSONObject actual, JSONObject expected, boolean virtual, boolean root, boolean children) throws Exception {
    Set<String> keys=new HashSet<>(expected.keySet());
    if(virtual){keys.add("virtualNodeId");keys.add("isVirtualFocusNode");}
    if(virtual&&root)keys.add("captureTimestamp");
    if(children)keys.add("children");
    check(keys.equals(actual.keySet()),"complete key contract");
    for(String key:expected.keySet()) {
      Object want=expected.get(key),got=actual.get(key);
      if(want instanceof JSONObject) {
        check(got instanceof JSONObject,"bounds object type");
        properties((JSONObject)got,(JSONObject)want,false,false,false);
      } else {
        check(want==JSONObject.NULL ? got==JSONObject.NULL : got.getClass()==want.getClass(),key+" exact wire type/null");
        check(want.equals(got),key+" value");
      }
    }
    if(virtual){check(actual.get("isVirtualFocusNode") instanceof Boolean,"focus boolean");UUID.fromString(actual.getString("virtualNodeId"));}
  }
  static AccessibilityNodeInfo node() {
    AccessibilityNodeInfo n=new AccessibilityNodeInfo();
    n.state.className="android.widget.Button";n.state.text="synthetic item";
    n.state.description="synthetic detail";n.state.viewId="synthetic:id/item";
    n.state.clickable=true;n.state.checkable=true;n.state.checked=false;n.state.focusable=false;
    n.state.enabled=true;n.state.password=false;n.state.selected=true;
    n.state.left=2;n.state.top=6;n.state.right=14;n.state.bottom=26;
    return n;
  }
  static void serializers() throws Exception {
    for(boolean nulls:new boolean[]{false,true}) {
      AccessibilityNodeInfo n=node();JSONObject expected=new JSONObject(EXPECTED);
      if(nulls) {
        n.state.className=null;n.state.text=null;n.state.description=null;n.state.viewId=null;
        for(String key:new String[]{"className","text","contentDescription","viewIdResourceName"})expected.put(key,JSONObject.NULL);
        n.state.clickable=false;n.state.checkable=false;n.state.checked=true;n.state.focusable=true;
        n.state.enabled=false;n.state.password=true;n.state.selected=false;
        for(String key:new String[]{"isClickable","isCheckable","isChecked","isFocusable","isEnabled","isPassword","isSelected"})expected.put(key,!expected.getBoolean(key));
      }
      AccessibilityNodeInfo child=node();n.add(child);
      for(boolean virtual:new boolean[]{false,true}) {
        int held=AccessibilityNodeInfo.outstandingCopies;
        JSONObject result=virtual?VirtualTreeBuilder.buildVirtualTree(n):RawNodeJsonHarness.accessibilityNodeInfoToJson(n);
        properties(result,expected,virtual,true,true);
        JSONObject children=result.getJSONObject("children");check(children.length()==1,"raw/virtual recurse to real child");
        properties(children.getJSONObject(children.keys().next()),new JSONObject(EXPECTED),virtual,false,false);
        check(AccessibilityNodeInfo.outstandingCopies==held,"serializer releases acquired child handles");
      }
    }
    check(RawNodeJsonHarness.accessibilityNodeInfoToJson(null)==null,"raw null root");
    check(VirtualTreeBuilder.buildVirtualTree(null)==null,"virtual null root");
  }
  static void singleNodeBoundary() throws Exception {
    Class<?> writer;
    try {writer=Class.forName("com.google.android.accessibility.utils.NodeProperties");}
    catch(ClassNotFoundException missing){throw new AssertionError("shared single-node property writer is absent",missing);}
    Method write=writer.getDeclaredMethod("write",AccessibilityNodeInfo.class,JSONObject.class);write.setAccessible(true);
    AccessibilityNodeInfo n=node();n.add(node());JSONObject result=new JSONObject();
    int reads=AccessibilityNodeInfo.childReads,copies=AccessibilityNodeInfo.outstandingCopies;
    write.invoke(null,n,result);
    properties(result,new JSONObject(EXPECTED),false,false,false);
    check(AccessibilityNodeInfo.childReads==reads&&AccessibilityNodeInfo.outstandingCopies==copies,"property writer neither walks nor owns child nodes");
  }
  public static void main(String[] args) throws Exception {
    serializers();singleNodeBoundary();
    System.out.println("node_field_contract_checks="+checks+" failures=0 native_device=NOT_RUN");
  }
}
