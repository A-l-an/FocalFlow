package com.google.android.accessibility.utils.output;
public interface SpeechController {
  class SpeakOptions {
    public int flags;
    public static SpeakOptions create() { return new SpeakOptions(); }
    public SpeakOptions setFlags(int flags) { this.flags=flags; return this; }
  }
}
