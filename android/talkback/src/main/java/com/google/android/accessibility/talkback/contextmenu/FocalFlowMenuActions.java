package com.google.android.accessibility.talkback.contextmenu;

import static com.google.android.accessibility.utils.Performance.EVENT_ID_UNTRACKED;

import android.content.Context;
import com.google.android.accessibility.talkback.Feedback;
import com.google.android.accessibility.talkback.Pipeline;
import com.google.android.accessibility.talkback.R;
import com.google.android.accessibility.utils.PcConnectionManager;
import com.google.android.accessibility.utils.SnapshotContext;
import com.google.android.accessibility.utils.VirtualTreeManager;
import com.google.android.accessibility.utils.output.FeedbackItem;
import com.google.android.accessibility.utils.output.SpeechController.SpeakOptions;
import java.util.concurrent.CompletableFuture;
import org.json.JSONObject;

/** Small adapter for the existing TalkBack menu and local speech pipeline. */
public final class FocalFlowMenuActions {
  private FocalFlowMenuActions() {}

  public static int titleResource() {
    return PcConnectionManager.getInstance().isFilteringPaused()
        ? R.string.focalflow_resume_ai : R.string.focalflow_restore_browsing;
  }

  public static boolean handle(int itemId) {
    if (itemId != R.id.focalflow_filtering) return false;
    PcConnectionManager pc = PcConnectionManager.getInstance();
    if (pc.isFilteringPaused()) pc.resumeFiltering();
    else pc.pauseFiltering();
    return true;
  }

  public static void menuOpened() { /* Opening a menu does not cancel the active capture. */ }

  public static boolean isCaptureAllowed(boolean menuExists) {
    return !menuExists && !PcConnectionManager.getInstance().isFilteringPaused();
  }

  public static boolean isCaptureCurrent(boolean menuExists, SnapshotContext capture) {
    return capture != null && !PcConnectionManager.getInstance().isFilteringPaused()
        && VirtualTreeManager.getInstance().isCurrent(capture);
  }

  /** Called on the main queue immediately before entering the existing speech pipeline. */
  public static boolean announce(Context context, Pipeline.FeedbackReturner pipeline,
      PcConnectionManager.RecoveryNotice notice) {
    if (!PcConnectionManager.getInstance().isRecoveryNoticeCurrent(notice)) return false;
    final int text;
    switch (notice.state) {
      case CONNECTED: text = R.string.focalflow_connected; break;
      case WAITING: text = R.string.focalflow_waiting; break;
      case PAUSED: text = R.string.focalflow_paused; break;
      case RESUMED: text = R.string.focalflow_resumed; break;
      case NATIVE: text = R.string.focalflow_standard_browsing; break;
      default: text = R.string.focalflow_failure_restored;
    }
    return speak(context, pipeline, text);
  }

  public static void requestDetails(Context context, Pipeline.FeedbackReturner pipeline) {
    PcConnectionManager pc = PcConnectionManager.getInstance();
    if (pc.isFilteringPaused()) { speak(context, pipeline, R.string.focalflow_paused); return; }
    CompletableFuture<JSONObject> request = pc.requestTalk();
    speak(context, pipeline, request.isCompletedExceptionally()
        ? R.string.focalflow_details_not_ready : R.string.focalflow_details_requested);
  }

  private static boolean speak(Context context, Pipeline.FeedbackReturner pipeline, int resource) {
    return pipeline.returnFeedback(EVENT_ID_UNTRACKED, Feedback.speech(context.getString(resource),
        SpeakOptions.create().setFlags(FeedbackItem.FLAG_NO_HISTORY
            | FeedbackItem.FLAG_FORCE_FEEDBACK_EVEN_IF_AUDIO_PLAYBACK_ACTIVE
            | FeedbackItem.FLAG_FORCE_FEEDBACK_EVEN_IF_MICROPHONE_ACTIVE
            | FeedbackItem.FLAG_FORCE_FEEDBACK_EVEN_IF_SSB_ACTIVE
            | FeedbackItem.FLAG_SKIP_DUPLICATE)));
  }
}
