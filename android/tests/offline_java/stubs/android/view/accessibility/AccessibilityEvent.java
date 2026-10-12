package android.view.accessibility;
public final class AccessibilityEvent {
 public static final int TYPE_WINDOW_STATE_CHANGED=32, TYPE_WINDOW_CONTENT_CHANGED=2048, TYPE_VIEW_SCROLLED=4096;
 public static final int CONTENT_CHANGE_TYPE_SUBTREE=1, CONTENT_CHANGE_TYPE_TEXT=2, CONTENT_CHANGE_TYPE_CONTENT_DESCRIPTION=4;
 public int type=TYPE_WINDOW_CONTENT_CHANGED, changes=CONTENT_CHANGE_TYPE_TEXT, windowId=1;
 public CharSequence packageName="synthetic.app"; public AccessibilityNodeInfo source;
 public int getEventType(){return type;} public int getContentChangeTypes(){return changes;}
 public int getWindowId(){return windowId;} public CharSequence getPackageName(){return packageName;}
 public AccessibilityNodeInfo getSource(){return source==null?null:AccessibilityNodeInfo.obtain(source);}
}
