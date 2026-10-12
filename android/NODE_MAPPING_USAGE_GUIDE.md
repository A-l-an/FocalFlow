> Historical background, not the current setup or acceptance guide. See
> [README.md](README.md) and [protocol v1](docs/protocol-v1.md) for the
> maintained candidate. Sensitive FocalFlow history is now off by default;
> transport snapshots, freshness checks and local pause/resume have changed.
> Examples below have not been revalidated and are not device-test evidence.

# 虚拟节点与实际节点双向映射使用指南

## 概述

`NodeMappingManager` 是一个专门用于管理虚拟节点和实际节点之间双向映射关系的管理器类。它提供了节点映射的创建、查询、更新、删除以及持久化存储功能，同时重点处理好节点的唯一标识和生命周期管理。

## 核心特性

1. **双向映射**: 支持虚拟节点 ID ↔ 实际节点的双向查找
2. **唯一标识**: 基于稳定的唯一标识符进行映射
3. **生命周期管理**: 自动处理节点失效和内存回收
4. **持久化存储**: 将映射关系保存到文件中便于调试
5. **与虚拟树集成**: 无缝集成到 `VirtualTreeBuilder` 中

## 快速开始

### 1. 初始化映射管理器

```java
import com.google.android.accessibility.utils.NodeMappingManager;
import com.google.android.accessibility.utils.VirtualTreeBuilder;

// 创建映射管理器
NodeMappingManager mappingManager = new NodeMappingManager(context);

// 设置会话信息（可选）
mappingManager.setSessionInfo("user123", "task456");

// 将映射管理器设置到VirtualTreeBuilder中（用于自动映射）
VirtualTreeBuilder.setMappingManager(mappingManager);
```

### 2. 基本用法

#### 方式一：通过 VirtualTreeBuilder 自动建立映射

```java
import org.json.JSONObject;

// 构建虚拟树时自动建立映射关系
JSONObject virtualTree = VirtualTreeBuilder.buildVirtualTree(rootNode);
// 映射关系已自动建立，无需额外操作
```

#### 方式二：手动添加映射关系

```java
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;

// 生成虚拟节点ID
String virtualNodeId = NodeMappingManager.generateVirtualNodeId();

// 手动添加映射关系
AccessibilityNodeInfoCompat actualNode = AccessibilityNodeInfoCompat.wrap(nodeInfo);
mappingManager.addMapping(virtualNodeId, actualNode);
```

### 3. 查询映射关系

#### 通过虚拟节点 ID 查找实际节点

```java
String virtualNodeId = "your-virtual-node-id";
AccessibilityNodeInfoCompat actualNode = mappingManager.getActualNode(virtualNodeId);

if (actualNode != null) {
    // 使用实际节点
    // 注意：使用完后需要回收
    actualNode.recycle();
}
```

#### 通过实际节点查找虚拟节点 ID

```java
AccessibilityNodeInfoCompat actualNode = // 你的实际节点
String virtualNodeId = mappingManager.getVirtualNodeId(actualNode);

if (virtualNodeId != null) {
    // 使用虚拟节点ID
}
```

## 核心概念

### 节点唯一标识符

#### 虚拟节点 ID (VirtualNodeKey)

- 使用 UUID 生成，格式如：`a1b2c3d4-e5f6-7890-abcd-ef1234567890`
- 在整个生命周期内保持稳定且唯一

#### 实际节点全局 ID (ActualNodeKey)

- 格式：`windowId_nodeId`
- `windowId`: 窗口 ID，通过 `AccessibilityNodeInfoCompat.getWindowId()` 获取
- `nodeId`: 节点 ID，优先使用 `getUniqueId()` (API 30+)，回退到哈希 ID

### 生命周期管理

1. **节点有效性检查**: 每次访问时自动检查节点是否仍然有效
2. **自动清理**: 当节点失效时自动移除映射关系
3. **内存回收**: 正确处理 `AccessibilityNodeInfoCompat` 的回收

## 详细 API 文档

### 核心方法

#### `addMapping(String virtualNodeId, AccessibilityNodeInfoCompat actualNode)`

添加虚拟节点和实际节点的映射关系。

**参数:**

- `virtualNodeId`: 虚拟节点 ID
- `actualNode`: 实际节点

**注意:** 如果 virtualNodeId 已存在，会先回收旧的节点再添加新的映射。

#### `getActualNode(String virtualNodeId)`

通过虚拟节点 ID 获取实际节点。

**返回:** 实际节点的拷贝，如果不存在或已失效则返回 null。使用完后需要调用 `recycle()`。

#### `getVirtualNodeId(AccessibilityNodeInfoCompat actualNode)`

通过实际节点获取虚拟节点 ID。

**返回:** 虚拟节点 ID，如果不存在则返回 null。

#### `removeMappingByVirtualId(String virtualNodeId)`

移除指定虚拟节点 ID 的映射关系。

#### `clearAllMappings()`

清空所有映射关系。

### 工具方法

#### `generateVirtualNodeId()`

生成新的虚拟节点 ID（UUID 格式）。

#### `generateActualNodeGlobalId(AccessibilityNodeInfoCompat node)`

为实际节点生成全局唯一 ID。

#### `setSessionInfo(String userId, String taskId)`

设置会话信息，用于文件存储的目录组织。

## 文件存储

### 存储位置

```
<app_external_files_dir>/screen_reader_logs/node_mappings/node_mapping_logs/
```

### 文件格式

```json
{
  "captureTimestamp": "123112345678",
  "userId": "user123",
  "taskId": "task456",
  "mappings": [
    {
      "virtualNodeId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "actualNodeGlobalId": "12_element_abc123def"
    }
  ]
}
```

### 文件命名

```
node_mappings_log_<userId>_<taskId>_<timestamp>.json
```

## 使用示例

### 完整工作流程示例

```java
public class AccessibilityServiceExample {
    private NodeMappingManager mappingManager;

    @Override
    public void onCreate() {
        super.onCreate();

        // 1. 初始化映射管理器
        mappingManager = new NodeMappingManager(this);
        mappingManager.setSessionInfo("user123", "session789");

        // 2. 设置到VirtualTreeBuilder
        VirtualTreeBuilder.setMappingManager(mappingManager);
    }

    public void processAccessibilityEvent(AccessibilityEvent event) {
        AccessibilityNodeInfo rootNode = getRootInActiveWindow();
        if (rootNode != null) {
            // 3. 构建虚拟树（自动建立映射）
            JSONObject virtualTree = VirtualTreeBuilder.buildVirtualTree(rootNode);

            // 4. 处理特定节点
            AccessibilityNodeInfo sourceNode = event.getSource();
            if (sourceNode != null) {
                AccessibilityNodeInfoCompat sourceCompat =
                    AccessibilityNodeInfoCompat.wrap(sourceNode);

                // 5. 查找对应的虚拟节点ID
                String virtualId = mappingManager.getVirtualNodeId(sourceCompat);
                if (virtualId != null) {
                    LogUtils.d(TAG, "Event from virtual node: " + virtualId);

                    // 6. 可以稍后通过虚拟ID反查实际节点
                    AccessibilityNodeInfoCompat actualNode =
                        mappingManager.getActualNode(virtualId);
                    if (actualNode != null) {
                        // 使用节点
                        actualNode.recycle(); // 记得回收
                    }
                }
            }
        }
    }
}
```

### 批量处理示例

```java
public void processBatchNodes(List<AccessibilityNodeInfo> nodes) {
    for (AccessibilityNodeInfo node : nodes) {
        if (node != null) {
            // 为每个节点生成虚拟ID并建立映射
            String virtualId = NodeMappingManager.generateVirtualNodeId();
            AccessibilityNodeInfoCompat nodeCompat = AccessibilityNodeInfoCompat.wrap(node);
            mappingManager.addMapping(virtualId, nodeCompat);

            LogUtils.d(TAG, "Added mapping for node: " + virtualId);
        }
    }
}
```

## 最佳实践

### 1. 内存管理

```java
// ✅ 正确：使用完后回收
AccessibilityNodeInfoCompat node = mappingManager.getActualNode(virtualId);
if (node != null) {
    // 使用节点
    node.recycle(); // 重要：回收资源
}

// ❌ 错误：没有回收会导致内存泄漏
AccessibilityNodeInfoCompat node = mappingManager.getActualNode(virtualId);
// 忘记调用 node.recycle()
```

### 2. 生命周期管理

```java
// ✅ 正确：检查节点有效性
AccessibilityNodeInfoCompat node = mappingManager.getActualNode(virtualId);
if (node != null) {
    // 节点仍然有效，可以安全使用
    performActionOnNode(node);
    node.recycle();
} else {
    // 节点已失效，映射已自动清理
    LogUtils.w(TAG, "Node is no longer valid");
}
```

### 3. 会话管理

```java
// ✅ 正确：设置有意义的会话信息
mappingManager.setSessionInfo("user_" + userId, "task_" + taskType + "_" + timestamp);

// ❌ 错误：使用无意义的会话信息
mappingManager.setSessionInfo("test", "test");
```

### 4. 错误处理

```java
try {
    String virtualId = NodeMappingManager.generateVirtualNodeId();
    mappingManager.addMapping(virtualId, actualNode);
} catch (Exception e) {
    LogUtils.e(TAG, "Failed to add mapping: " + e.getMessage(), e);
    // 适当的错误处理
}
```

## 注意事项

1. **AccessibilityNodeInfoCompat 回收**: 获取的节点使用完后必须调用 `recycle()`
2. **节点有效性**: 节点可能随时失效，总是检查返回值是否为 null
3. **性能考虑**: 映射关系存储在内存中，大量节点时注意内存使用
4. **线程安全**: 当前实现非线程安全，在多线程环境下需要额外同步
5. **文件存储**: 每次映射变化都会写文件，频繁操作时考虑性能影响

## 调试技巧

### 1. 查看映射文件

映射关系会自动保存到文件中，可以通过 adb 或文件管理器查看：

```bash
adb shell cat /sdcard/Android/data/<package_name>/files/screen_reader_logs/node_mappings/node_mapping_logs/node_mappings_log_*.json
```

### 2. 日志输出

启用 DEBUG 日志查看详细的映射操作：

```java
// 在代码中查看日志输出
LogUtils.d(TAG, "Current mapping count: " + mappingManager.getMappingCount());
```

### 3. 验证映射完整性

```java
// 验证双向映射的一致性
String virtualId = mappingManager.getVirtualNodeId(actualNode);
if (virtualId != null) {
    AccessibilityNodeInfoCompat retrievedNode = mappingManager.getActualNode(virtualId);
    if (retrievedNode != null) {
        LogUtils.d(TAG, "Bidirectional mapping verified");
        retrievedNode.recycle();
    }
}
```

## 故障排除

### 常见问题

#### 1. 节点映射丢失

**原因**: 节点失效导致映射被自动清理
**解决**: 检查节点生命周期，确保在节点有效期内使用

#### 2. 内存泄漏

**原因**: 忘记回收 AccessibilityNodeInfoCompat
**解决**: 总是在 finally 块中回收节点

#### 3. 映射文件过多

**原因**: 频繁的映射操作导致大量文件生成
**解决**: 考虑批量操作或减少映射频率

#### 4. 性能问题

**原因**: 大量节点同时映射
**解决**: 分批处理，适当清理不再需要的映射

---

通过遵循本指南，您可以有效地使用 `NodeMappingManager` 在虚拟节点和实际节点之间建立稳定的双向映射关系，并确保良好的性能和资源管理。
