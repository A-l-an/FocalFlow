package android.view.accessibility;
import android.graphics.Rect;
import java.util.*;
/** Synthetic native identity plus mutable provider state, not a native Android traversal claim. */
public class AccessibilityNodeInfo {
 public static int propertyReads, outstandingCopies, childReads;
 public static Runnable onRefresh;
 public static RuntimeException propertyFailure;
 public final Object identity; public final State state; private boolean owned,recycled;
 public static final class State {
  public String text="synthetic", description="", viewId="synthetic:id", className="android.widget.TextView", packageName="synthetic.app";
  public int windowId=1; public boolean visible=true, clickable=true,checkable,checked,focusable=true,enabled=true,password,selected,scrollable,valid=true;
  public int left=0,top=0,right=10,bottom=10;
  public AccessibilityNodeInfo parent; public List<AccessibilityNodeInfo> children=new ArrayList<>();
 }
 public AccessibilityNodeInfo(){identity=new Object();state=new State();}
 private AccessibilityNodeInfo(AccessibilityNodeInfo n){identity=n.identity;state=n.state;owned=true;outstandingCopies++;}
 public static AccessibilityNodeInfo obtain(AccessibilityNodeInfo n){return new AccessibilityNodeInfo(n);}
 public boolean equals(Object o){return o instanceof AccessibilityNodeInfo&&((AccessibilityNodeInfo)o).identity==identity;}
 public int hashCode(){return 7;} // Intentional collisions: hashes cannot prove native identity.
 public void recycle(){if(owned&&!recycled){recycled=true;outstandingCopies--;}}
 public boolean refresh(){if(onRefresh!=null)onRefresh.run();return state.valid;}
 public void add(AccessibilityNodeInfo n){state.children.add(n);n.state.parent=this;}
 public int getChildCount(){return state.children.size();}
 public AccessibilityNodeInfo getChild(int i){childReads++;return obtain(state.children.get(i));}
 public AccessibilityNodeInfo getParent(){return state.parent==null?null:obtain(state.parent);}
 public String getUniqueId(){return "synthetic-uid-"+System.identityHashCode(identity);}
 public CharSequence getPackageName(){return state.packageName;} public int getWindowId(){return state.windowId;}
 public CharSequence getClassName(){propertyReads++;if(propertyFailure!=null)throw propertyFailure;return state.className;}
 public CharSequence getText(){propertyReads++;return state.text;} public CharSequence getContentDescription(){return state.description;}
 public String getViewIdResourceName(){return state.viewId;}
 public boolean isVisibleToUser(){return state.visible;} public boolean isClickable(){return state.clickable;}
 public boolean isCheckable(){return state.checkable;} public boolean isChecked(){return state.checked;}
 public boolean isFocusable(){return state.focusable;} public boolean isEnabled(){return state.enabled;}
 public boolean isPassword(){return state.password;} public boolean isSelected(){return state.selected;}
 public boolean isScrollable(){return state.scrollable;}
 public void getBoundsInScreen(Rect r){r.left=state.left;r.top=state.top;r.right=state.right;r.bottom=state.bottom;}
}
