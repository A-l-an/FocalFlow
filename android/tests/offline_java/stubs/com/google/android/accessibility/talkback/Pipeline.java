package com.google.android.accessibility.talkback;
import com.google.android.accessibility.utils.Performance.EventId;
public final class Pipeline {
  public interface FeedbackReturner { boolean returnFeedback(EventId event, Feedback.Part.Builder part); }
}
