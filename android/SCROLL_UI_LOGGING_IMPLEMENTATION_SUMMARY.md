> Historical background, not the current setup or acceptance guide. See
> [README.md](README.md) and [protocol v1](docs/protocol-v1.md) for the
> maintained candidate. Sensitive FocalFlow history is now off by default;
> transport snapshots, freshness checks and local pause/resume have changed.
> Examples below have not been revalidated and are not device-test evidence.

# 滚动事件触发 UI 记录功能实现总结

## 实现目标

为 TalkBack 的 UI 元素记录功能添加第三个触发时机：滚动事件发生后。

现在 UI 元素保存的完整触发时机为：

1. **双击操作后** (最高优先级)
2. **滚动事件后** (中等优先级，2 秒节流)
3. **TYPE_WINDOW_STATE_CHANGED** (最低优先级)

## 修改的文件

### 1. utils/src/main/java/com/google/android/accessibility/utils/DelayHandler.java

**新增内容：**

- 添加滚动事件消息类型：`MSG_WHAT_DELAYED_LOG_AFTER_SCROLL = 5`
- 添加滚动事件节流常量：`SCROLL_EVENT_THROTTLE_MS = 2000` (2 秒)
- 添加滚动事件状态跟踪：`lastScrollEventTime`
- 在 `handleMessage` 中添加滚动事件处理分支
- 新增 `delayLogUiElementsAfterScroll()` 方法
- 修改 `cancelAllDelayedLogging()` 方法，包含滚动消息的取消

**关键代码：**

```java
case MSG_WHAT_DELAYED_LOG_AFTER_SCROLL:
  isUiElementsLogPending = false;
  isVirtualTreeLogPending = false;
  if (uiElementsLogCallback != null) {
    Log.d(TAG, "执行滚动操作后的UI元素延迟记录");
    uiElementsLogCallback.onLogUiElements("scroll");
  }
  if (virtualTreeLogCallback != null) {
    Log.d(TAG, "执行滚动操作后的虚拟树延迟记录");
    virtualTreeLogCallback.onLogVirtualTree("scroll");
  }
  break;

public void delayLogUiElementsAfterScroll() {
  handler.removeMessages(MSG_WHAT_DELAYED_LOG_AFTER_SCROLL);

  if (uiElementsLogCallback != null || virtualTreeLogCallback != null) {
    Log.d(TAG, "安排滚动操作后延迟记录UI元素和虚拟树，延迟时间：" + DEFAULT_UI_LOGGING_DELAY_MS + "ms");
    isUiElementsLogPending = true;
    isVirtualTreeLogPending = true;
    handler.sendMessageDelayed(
        handler.obtainMessage(MSG_WHAT_DELAYED_LOG_AFTER_SCROLL),
        DEFAULT_UI_LOGGING_DELAY_MS);
  }
}
```

### 2. talkback/src/main/java/com/google/android/accessibility/talkback/TalkBackService.java

**新增内容：**

- 添加滚动事件状态跟踪变量：
  - `lastScrollTime` - 最后滚动时间
  - `SCROLL_PRIORITY_WINDOW_MS = 1500` - 滚动优先级窗口 1.5 秒
- 在 `onAccessibilityEvent` 中添加 `TYPE_VIEW_SCROLLED` 事件处理
- 新增 `shouldLogScrollUI()` 方法进行滚动事件过滤
- 修改 `shouldLogWindowChangeUI()` 方法添加滚动优先级判断
- 修改 `logUIElementsToFile()` 和 `logVirtualTreeToFile()` 方法支持 `"scroll"` 触发原因

**关键代码：**

```java
// 处理滚动事件的UI元素记录
if (event.getEventType() == AccessibilityEvent.TYPE_VIEW_SCROLLED) {
  if (shouldLogScrollUI(event)) {
    String eventTypeStr = "视图滚动";
    Log.d(TAG, eventTypeStr + "，安排延迟记录UI元素和虚拟树");
    if (uiLoggingDelayHandler != null) {
      uiLoggingDelayHandler.delayLogUiElementsAfterScroll();
    }
  }
}

private boolean shouldLogScrollUI(AccessibilityEvent event) {
  long currentTime = System.currentTimeMillis();

  // 检查是否在双击优先级窗口内
  if (doubleTapTriggered && (currentTime - lastDoubleTapTime) < DOUBLE_TAP_PRIORITY_WINDOW_MS) {
    return false;
  }

  // 检查是否为系统UI事件
  if (isSystemUIEvent(event)) {
    return false;
  }

  // 更新滚动时间戳
  lastScrollTime = currentTime;
  return true;
}
```

## 优先级控制机制

### 事件优先级顺序：

1. **双击操作** (最高优先级，3 秒窗口)
2. **滚动事件** (中等优先级，1.5 秒窗口)
3. **窗口状态变化** (最低优先级)

### 节流机制：

- **滚动事件**：DelayHandler 内部 2 秒节流，防止连续滚动产生过多记录
- **窗口事件**：1 秒节流，防止频繁窗口变化
- **双击事件**：无节流，但有 3 秒优先级窗口

### 过滤机制：

- 系统 UI 事件过滤：跳过来自系统 UI 的所有事件
- 优先级窗口过滤：低优先级事件在高优先级窗口内被跳过

## 日志输出示例

### 滚动事件触发的记录：

```
D/TalkBackService: 视图滚动，安排延迟记录UI元素和虚拟树
D/DelayHandler: 安排滚动操作后延迟记录UI元素和虚拟树，延迟时间：2000ms
D/DelayHandler: 执行滚动操作后的UI元素延迟记录
D/DelayHandler: 执行滚动操作后的虚拟树延迟记录
D/TalkBackService: UI元素层次结构已记录到文件 - 触发原因：滚动操作
D/TalkBackService: 虚拟树结构已记录到文件 - 触发原因：滚动操作
```

### 优先级控制的记录：

```
D/TalkBackService: 双击手势触发，安排延迟记录UI元素和虚拟树
(此时如果有滚动事件，会被跳过)
D/TalkBackService: 视图滚动，安排延迟记录UI元素和虚拟树
(此时如果有窗口变化事件，会被跳过)
```

## 技术特点

1. **无侵入性**：不影响现有的双击和窗口变化触发机制
2. **智能优先级**：确保不会产生重复记录，高优先级事件优先
3. **性能优化**：多层节流机制避免过度记录
4. **完整过滤**：系统 UI 事件过滤避免不必要的记录
5. **延迟记录**：2 秒延迟确保 UI 状态稳定后再记录
6. **统一接口**：使用相同的回调接口和文件记录机制

## 编译验证

- ✅ utils 模块编译成功
- ✅ talkback 模块编译成功
- ✅ 无语法错误
- ✅ 保持向下兼容性

## 使用场景

滚动触发的 UI 记录特别适用于：

- 列表滚动后的内容变化记录
- 网页滚动后的新元素记录
- 滚动视图中焦点变化的记录
- 长页面导航过程的 UI 状态记录

这个功能完善了 TalkBack 的 UI 记录能力，能够更全面地捕获用户交互过程中的 UI 状态变化。
