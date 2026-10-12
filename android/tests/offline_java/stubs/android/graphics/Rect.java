package android.graphics;
public final class Rect { public int left,top,right,bottom;
 public int centerX(){return (left+right)/2;} public int centerY(){return (top+bottom)/2;}
 public boolean equals(Object o){if(!(o instanceof Rect))return false;Rect r=(Rect)o;return left==r.left&&top==r.top&&right==r.right&&bottom==r.bottom;}
}
