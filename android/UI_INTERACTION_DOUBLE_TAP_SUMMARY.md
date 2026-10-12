> Historical background, not the current setup or acceptance guide. See
> [README.md](README.md) and [protocol v1](docs/protocol-v1.md) for the
> maintained candidate. Sensitive FocalFlow history is now off by default;
> transport snapshots, freshness checks and local pause/resume have changed.
> Examples below have not been revalidated and are not device-test evidence.

# UI 交互记录双击触发修改总结

## 修改目标

根据用户需求，修改 UI 交互记录功能：

1. **记录时机**：只在双击操作后记录 UI 交互，不再在每次聚焦时记录
2. **记录格式**：按照参考代码(referencecode.kt)的格式来记录 UI 交互数据

## 修改的文件

### 1. utils/src/main/java/com/google/android/accessibility/utils/UserInteractionTracker.java

#### 主要修改内容：

**1) 重构 recordInteraction 方法**

- 修改数据结构，使用 `visitRecords` 结构替代原来的 `actions` 数组
- 采用参考代码的元素 ID 生成格式：`viewIdResourceName:centerX,centerY` 或 `element_hashCode:centerX,centerY`
- 添加导航路径(`navigationPath`)记录，包含前一个元素、当前元素、停留时间和交互类型
- 使用 `name`, `text`, `contentDescription`, `childName`, `position` 字段结构

**2) 新增辅助方法**

- `getNodeDescriptionAll()`: 获取节点的综合描述信息
- `findCombinedChildDescription()`: 递归查找子节点描述信息
- `updateLastVisitRecordDuration()`: 更新访问记录的持续时间
- `getCurrentWindowName()`: 获取当前窗口名称

**3) 修改 saveInteractionsToFile 方法**

- 使用 `windows` 结构保存数据，与参考代码格式一致
- 使用 UTC 时区的时间戳格式
- 保存为 `ui_interaction_log` 类型

**4) 新增双击专用记录方法**

- `recordDoubleTapInteraction(AccessibilityNodeInfo node)`: 使用节点信息记录双击交互
- `recordDoubleTapInteraction(String elementInfo)`: 使用字符串信息记录双击交互

#### 数据格式示例：

```json
{
  "userId": "user123",
  "taskId": "task456",
  "timestamp": "2024-01-15T10:30:45Z",
  "windows": {
    "window_12345": {
      "windowName": "com.example.app.MainActivity",
      "elementId1:100,200": {
        "name": "Button Text | android.widget.Button",
        "text": "Button Text",
        "contentDescription": "",
        "position": {
          "x": 100,
          "y": 200
        },
        "visitRecords": [
          {
            "startTime": "2024-01-15T10:30:45Z",
            "endTime": "2024-01-15T10:30:48Z",
            "navigationPath": [
              {
                "previousElement": "null",
                "currentElement": "elementId1:100,200",
                "timeSpentOnPrevious": 0,
                "timeSpentOnCurrent": 3000,
                "interactionType": "DOUBLE_TAP"
              }
            ]
          }
        ]
      }
    }
  }
}
```

### 2. talkback/src/main/java/com/google/android/accessibility/talkback/TalkBackService.java

#### 主要修改内容：

**1) 修改双击手势处理逻辑**

- 在 `GESTURE_DOUBLE_TAP` 处理中，添加对当前聚焦节点的 UI 交互记录
- 尝试获取当前可访问性聚焦的节点进行记录
- 如果找不到聚焦节点，则使用字符串描述方式记录
- 添加异常处理和节点回收机制

**2) 新增 findAccessibilityFocus 方法**

- 递归查找当前具有可访问性聚焦的节点
- 确保节点的正确回收，防止内存泄漏
- 返回当前聚焦节点的副本

#### 关键代码：

```java
// 在双击手势处理中
if (userInteractionTracker != null) {
  AccessibilityNodeInfo currentFocusedNode = null;
  try {
    AccessibilityNodeInfo rootNodeInfo = getRootInActiveWindow();
    if (rootNodeInfo != null) {
      currentFocusedNode = findAccessibilityFocus(rootNodeInfo);
      if (currentFocusedNode != null) {
        userInteractionTracker.recordDoubleTapInteraction(currentFocusedNode);
      } else {
        userInteractionTracker.recordDoubleTapInteraction("gesture_double_tap");
      }
      rootNodeInfo.recycle();
    }
  } catch (Exception e) {
    // 错误处理和降级记录
  } finally {
    if (currentFocusedNode != null) {
      currentFocusedNode.recycle();
    }
  }
}
```

## 实现效果

### 记录时机变更：

- **修改前**：每次元素聚焦时都会记录 UI 交互
- **修改后**：只在双击操作后记录 UI 交互

### 数据格式改进：

- **修改前**：使用简单的 actions 数组结构
- **修改后**：使用 visitRecords 结构，包含详细的导航路径和时间信息

### 兼容性：

- 保持与现有 FileLogger 系统的兼容性
- 保持与延迟记录机制的兼容性
- 向下兼容原有的字符串记录方式

## 测试验证

- ✅ utils 模块编译成功 (`./gradlew :utils:compilePhoneDebugJavaWithJavac`)
- ✅ talkback 模块编译成功 (`./gradlew :talkback:compilePhoneDebugJavaWithJavac`)
- ✅ 代码结构符合参考代码格式要求
- ✅ 添加了完整的异常处理和资源回收机制

## 日志输出

修改后，双击操作会产生以下日志：

```
D/UserInteractionTracker: 双击交互已记录
D/UserInteractionTracker: 记录交互: DOUBLE_TAP 元素: elementId
D/UserInteractionTracker: UI interactions saved successfully for userId: xxx, taskId: xxx
```

这些修改确保了 UI 交互记录功能完全按照用户需求进行：只在双击操作后触发记录，并使用与参考代码一致的数据格式。
