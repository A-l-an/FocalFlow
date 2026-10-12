package android.os;
import java.util.*;
public class Handler {
 static class Entry { Handler h; Message m; long due; Entry(Handler h,Message m,long d){this.h=h;this.m=m;due=d;} }
 static List<Entry> queue=new ArrayList<>(); public static long now;
 public Handler(Looper l){} public void handleMessage(Message m){}
 public Message obtainMessage(int w){return new Message(w,null);} public Message obtainMessage(int w,Object o){return new Message(w,o);}
 public boolean hasMessages(int w){return queue.stream().anyMatch(e->e.h==this&&e.m.what==w);}
 public void removeMessages(int w){queue.removeIf(e->e.h==this&&e.m.what==w);}
 public void removeCallbacksAndMessages(Object o){queue.removeIf(e->e.h==this);}
 public boolean sendMessageDelayed(Message m,long delay){queue.add(new Entry(this,m,now+delay));return true;}
 public static void advance(long t){
  for(;;){Entry next=null; for(Entry e:queue) if(e.due<=t&&(next==null||e.due<next.due))next=e;
   if(next==null)break;queue.remove(next);now=next.due;next.h.handleMessage(next.m);
  }now=t;
 }
 public static void reset(){queue.clear();now=0;}
}