package com.google.android.accessibility.talkback;
import com.google.android.accessibility.utils.output.SpeechController.SpeakOptions;
public final class Feedback {
  public static final class Part {
    public static final class Builder {
      public final CharSequence text;
      public final SpeakOptions options;
      public Builder(CharSequence text, SpeakOptions options) { this.text=text; this.options=options; }
    }
  }
  public static Part.Builder speech(CharSequence text, SpeakOptions options) { return new Part.Builder(text, options); }
}
