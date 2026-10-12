/*
 * Copyright (C) 2017 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy of
 * the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
 * License for the specific language governing permissions and limitations under
 * the License.
 */

package com.google.android.accessibility.utils;

import android.os.Handler;
import android.os.Looper;
import android.os.Message;
import android.util.Log;
import android.view.accessibility.AccessibilityNodeInfo;

import androidx.annotation.Nullable;

/**
 * Utility class that handles delays. It's mainly used to handle a delay before
 * performing an action.
 */
public abstract class DelayHandler<T> {

  private static final String TAG = "DelayHandler";

  /** Messages for handling delayed actions. */
  private static final int MSG_WHAT_EXECUTE_RUNNABLE = 1;
  private static final int MSG_WHAT_DELAYED_LOG_UI_ELEMENTS = 2;
  private static final int MSG_WHAT_DELAYED_LOG_AFTER_DOUBLE_TAP = 3;
  private static final int MSG_WHAT_GENERIC_HANDLER = 4;
  private static final int MSG_WHAT_DELAYED_LOG_AFTER_SCROLL = 5;

  // 延迟记录UI元素和虚拟树的默认时间（毫秒）
  public static final int DEFAULT_UI_LOGGING_DELAY_MS = 2000;

  // 滚动事件节流间隔（毫秒）
  private static final long SCROLL_EVENT_THROTTLE_MS = 2000;

  // 接口定义：UI元素记录回调
  public interface UiElementsLogCallback {
    void onLogUiElements(String triggerReason);
  }
  
  private UiElementsLogCallback uiElementsLogCallback;
  
  // 添加记录状态跟踪，防止重复记录
  private volatile boolean isUiElementsLogPending = false;
  private volatile boolean isVirtualTreeLogPending = false;
  
  // 添加滚动事件状态跟踪
  private volatile long lastScrollEventTime = 0;
  
  // 内部Handler类实现消息处理
  private class MainThreadHandler extends Handler {
    
    public MainThreadHandler() {
      super(Looper.getMainLooper());
    }
    
    @Override
    public void handleMessage(Message msg) {
      switch (msg.what) {
        case MSG_WHAT_EXECUTE_RUNNABLE:
          if (msg.obj instanceof Runnable) {
            ((Runnable) msg.obj).run();
          }
          break;
        case MSG_WHAT_DELAYED_LOG_UI_ELEMENTS:
          isUiElementsLogPending = false;
          isVirtualTreeLogPending = false;
          if (uiElementsLogCallback != null) {
            Log.d(TAG, "执行窗口内容变化后的UI元素延迟记录");
            uiElementsLogCallback.onLogUiElements("ui_change");
          }
          break;
        case MSG_WHAT_DELAYED_LOG_AFTER_DOUBLE_TAP:
          isUiElementsLogPending = false;
          isVirtualTreeLogPending = false;
          if (msg.obj instanceof Runnable) {
            ((Runnable) msg.obj).run();
          } else if (uiElementsLogCallback != null) {
            Log.d(TAG, "执行双击操作后的UI元素延迟记录");
            uiElementsLogCallback.onLogUiElements("double_tap");
          }
          break;
        case MSG_WHAT_GENERIC_HANDLER:
          @SuppressWarnings("unchecked")
          T handlerArg = (T) msg.obj;
          handle(handlerArg);
          break;
        case MSG_WHAT_DELAYED_LOG_AFTER_SCROLL:
          isUiElementsLogPending = false;
          isVirtualTreeLogPending = false;
          if (uiElementsLogCallback != null) {
            Log.d(TAG, "执行滚动操作后的UI元素延迟记录");
            uiElementsLogCallback.onLogUiElements("scroll");
          }
          break;
        default:
          break;
      }
    }
  }

  private final Handler handler;

  public DelayHandler() {
    this.uiElementsLogCallback = null;
    this.handler = new MainThreadHandler();
  }
  
  /**
   * 设置UI元素日志回调
   * @param callback UI元素日志回调接口
   */
  public void setUiElementsLogCallback(UiElementsLogCallback callback) {
    this.uiElementsLogCallback = callback;
    Log.d(TAG, "UI元素日志回调已设置: " + (callback != null ? "已设置" : "已清除"));
  }

  /**
   * Abstract method to be implemented by subclasses for handling delayed actions with typed arguments.
   *
   * @param arg the typed argument to handle
   */
  public abstract void handle(T arg);

  /**
   * Delays the execution of handle() with the specified argument.
   *
   * @param delayMs the delay in milliseconds
   * @param handlerArg the typed argument to pass to handle()
   */
  public void delay(long delayMs, T handlerArg) {
    // Remove any pending posts of this message type.
    handler.removeMessages(MSG_WHAT_GENERIC_HANDLER);

    Message msg = handler.obtainMessage(MSG_WHAT_GENERIC_HANDLER, handlerArg);
    handler.sendMessageDelayed(msg, delayMs);
  }

  /**
   * Performs a given {@code runnable} after {@code delayMs} milliseconds. If this method is called
   * again before the {@code runnable} is executed, the first one will be removed.
   *
   * @param runnable the runnable object containing code to run.
   * @param delayMs the time (in milliseconds) to wait before executing the runnable.
   */
  public void delay(Runnable runnable, int delayMs) {
    // Remove any pending posts of Runnable.
    handler.removeMessages(MSG_WHAT_EXECUTE_RUNNABLE);

    Message msg = handler.obtainMessage(MSG_WHAT_EXECUTE_RUNNABLE, runnable);
    handler.sendMessageDelayed(msg, delayMs);
  }

  /**
   * Cancels all delayed callback.
   */
  public void removeMessages() {
    handler.removeCallbacksAndMessages(null);
    isUiElementsLogPending = false;
    isVirtualTreeLogPending = false;
  }

  /**
   * 在窗口内容变化后延迟记录UI元素和虚拟树
   * 同一批窗口和滚动通知共用首次通知的截止时间，避免持续通知饿死采集。
   */
  public void delayLogUiElementsAfterWindowChange() {
    if (isCapturePending()) return;
    
    // 创建并发送新消息
    if (uiElementsLogCallback != null) {
      Log.d(TAG, "安排窗口内容变化后延迟记录UI元素和虚拟树，延迟时间：" + DEFAULT_UI_LOGGING_DELAY_MS + "ms");
      isUiElementsLogPending = true;
      isVirtualTreeLogPending = true;
      handler.sendMessageDelayed(
          handler.obtainMessage(MSG_WHAT_DELAYED_LOG_UI_ELEMENTS), 
          DEFAULT_UI_LOGGING_DELAY_MS);
    } else {
      Log.w(TAG, "UI元素日志回调未设置，无法安排延迟记录");
    }
  }
  
  /**
   * 在双击操作后延迟记录UI元素和虚拟树
   * 如果在延迟期间又收到相同请求，则取消上一次请求，重新计时
   */
  public void delayLogUiElementsAfterDoubleTap() {
    // 移除之前的相同类型的消息
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_AFTER_DOUBLE_TAP);
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_UI_ELEMENTS);
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_AFTER_SCROLL);
    
    // 创建并发送新消息
    if (uiElementsLogCallback != null) {
      Log.d(TAG, "安排双击操作后延迟记录UI元素和虚拟树，延迟时间：" + DEFAULT_UI_LOGGING_DELAY_MS + "ms");
      isUiElementsLogPending = true;
      isVirtualTreeLogPending = true;
      handler.sendMessageDelayed(
          handler.obtainMessage(MSG_WHAT_DELAYED_LOG_AFTER_DOUBLE_TAP), 
          DEFAULT_UI_LOGGING_DELAY_MS);
    } else {
      Log.w(TAG, "UI元素日志回调未设置，无法安排延迟记录");
    }
  }

  /** Keep interaction capture independent of generic priority-reset callbacks. */
  protected void delayDoubleTapCapture(Runnable runnable, int delayMs) {
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_UI_ELEMENTS);
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_AFTER_SCROLL);
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_AFTER_DOUBLE_TAP);
    isUiElementsLogPending = true;
    isVirtualTreeLogPending = true;
    handler.sendMessageDelayed(handler.obtainMessage(MSG_WHAT_DELAYED_LOG_AFTER_DOUBLE_TAP, runnable), delayMs);
  }

  private boolean isCapturePending() {
    return handler.hasMessages(MSG_WHAT_DELAYED_LOG_UI_ELEMENTS)
        || handler.hasMessages(MSG_WHAT_DELAYED_LOG_AFTER_SCROLL)
        || handler.hasMessages(MSG_WHAT_DELAYED_LOG_AFTER_DOUBLE_TAP);
  }

  /**
   * 取消所有待处理的延迟记录操作
   */
  public void cancelAllDelayedLogging() {
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_UI_ELEMENTS);
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_AFTER_DOUBLE_TAP);
    handler.removeMessages(MSG_WHAT_DELAYED_LOG_AFTER_SCROLL);
    isUiElementsLogPending = false;
    isVirtualTreeLogPending = false;
    Log.d(TAG, "已取消所有待处理的延迟记录操作");
  }

  /**
   * 在滚动操作后延迟记录UI元素和虚拟树
   * 与窗口通知合并，保留首次通知的截止时间。
   */
  public void delayLogUiElementsAfterScroll() {
    if (isCapturePending()) return;
    
    // 创建并发送新消息
    if (uiElementsLogCallback != null) {
      Log.d(TAG, "安排滚动操作后延迟记录UI元素和虚拟树，延迟时间：" + DEFAULT_UI_LOGGING_DELAY_MS + "ms");
      isUiElementsLogPending = true;
      isVirtualTreeLogPending = true;
      handler.sendMessageDelayed(
          handler.obtainMessage(MSG_WHAT_DELAYED_LOG_AFTER_SCROLL), 
          DEFAULT_UI_LOGGING_DELAY_MS);
    } else {
      Log.w(TAG, "UI元素日志回调未设置，无法安排延迟记录");
    }
  }
}
