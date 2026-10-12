package com.google.android.accessibility.utils;

import android.content.Context;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import com.google.android.libraries.accessibility.utils.log.LogUtils;
import org.json.JSONObject;

/**
 * 使用NodeMappingManager的示例类
 * 展示如何在虚拟节点和实际节点之间建立双向映射关系
 */
public class NodeMappingExample {

    private static final String TAG = "NodeMappingExample";
    private NodeMappingManager mappingManager;

    public NodeMappingExample(Context context) {
        // 初始化映射管理器
        mappingManager = new NodeMappingManager(context);
        
        // 设置会话信息
        mappingManager.setSessionInfo("user123", "task456");
        
        // 将映射管理器设置到VirtualTreeBuilder中
        VirtualTreeBuilder.setMappingManager(mappingManager);
        
        LogUtils.d(TAG, "NodeMappingExample initialized");
    }

    /**
     * 示例1：构建虚拟树并自动建立映射关系
     * @param rootNode 根节点
     * @return 虚拟树JSON对象
     */
    public JSONObject buildVirtualTreeWithMapping(AccessibilityNodeInfo rootNode) {
        if (rootNode == null) {
            LogUtils.w(TAG, "Root node is null, cannot build virtual tree");
            return null;
        }

        // 构建虚拟树，会自动建立映射关系
        JSONObject virtualTree = VirtualTreeBuilder.buildVirtualTree(rootNode);
        
        if (virtualTree != null) {
            LogUtils.d(TAG, "Virtual tree built with automatic mapping");
        }
        
        return virtualTree;
    }

    /**
     * 示例2：手动添加映射关系
     * @param actualNode 实际节点
     */
    public void addMappingManually(AccessibilityNodeInfoCompat actualNode) {
        if (actualNode == null) {
            LogUtils.w(TAG, "Actual node is null, cannot add mapping");
            return;
        }

        // 生成虚拟节点ID
        String virtualNodeId = NodeMappingManager.generateVirtualNodeId();
        
        // 添加映射关系
        mappingManager.addMapping(virtualNodeId, actualNode);
        
        LogUtils.d(TAG, "Manual mapping added: virtualId=%s", virtualNodeId);
    }

    /**
     * 示例3：通过虚拟节点ID查找实际节点
     * @param virtualNodeId 虚拟节点ID
     * @return 实际节点，如果不存在或已失效则返回null
     */
    public AccessibilityNodeInfoCompat findActualNodeByVirtualId(String virtualNodeId) {
        AccessibilityNodeInfoCompat actualNode = mappingManager.getActualNode(virtualNodeId);
        
        if (actualNode != null) {
            LogUtils.d(TAG, "Found actual node for virtualId: %s", virtualNodeId);
        } else {
            LogUtils.w(TAG, "No actual node found for virtualId: %s", virtualNodeId);
        }
        
        return actualNode;
    }

    /**
     * 示例4：通过实际节点查找虚拟节点ID
     * @param actualNode 实际节点
     * @return 虚拟节点ID，如果不存在则返回null
     */
    public String findVirtualIdByActualNode(AccessibilityNodeInfoCompat actualNode) {
        String virtualNodeId = mappingManager.getVirtualNodeId(actualNode);
        
        if (virtualNodeId != null) {
            LogUtils.d(TAG, "Found virtual ID for actual node: %s", virtualNodeId);
        } else {
            LogUtils.w(TAG, "No virtual ID found for actual node");
        }
        
        return virtualNodeId;
    }

    /**
     * 示例5：移除映射关系
     * @param virtualNodeId 要移除的虚拟节点ID
     */
    public void removeMappingExample(String virtualNodeId) {
        mappingManager.removeMappingByVirtualId(virtualNodeId);
        LogUtils.d(TAG, "Removed mapping for virtualId: %s", virtualNodeId);
    }

    /**
     * 示例6：清空所有映射关系
     */
    public void clearAllMappingsExample() {
        mappingManager.clearAllMappings();
        LogUtils.d(TAG, "Cleared all mappings");
    }

    /**
     * 示例7：批量处理节点并建立映射关系
     * @param nodes 节点数组
     */
    public void batchProcessNodes(AccessibilityNodeInfoCompat[] nodes) {
        if (nodes == null || nodes.length == 0) {
            LogUtils.w(TAG, "No nodes to process");
            return;
        }

        LogUtils.d(TAG, "Starting batch processing of %d nodes", nodes.length);
        
        for (int i = 0; i < nodes.length; i++) {
            AccessibilityNodeInfoCompat node = nodes[i];
            if (node != null) {
                String virtualNodeId = "batch_node_" + i + "_" + System.currentTimeMillis();
                mappingManager.addMapping(virtualNodeId, node);
                LogUtils.d(TAG, "Processed node %d with virtualId: %s", i, virtualNodeId);
            }
        }
        
        LogUtils.d(TAG, "Batch processing completed");
    }

    /**
     * 示例8：节点生命周期管理示例
     * @param actualNode 实际节点
     */
    public void nodeLifecycleExample(AccessibilityNodeInfoCompat actualNode) {
        if (actualNode == null) {
            return;
        }

        // 1. 建立映射
        String virtualNodeId = NodeMappingManager.generateVirtualNodeId();
        mappingManager.addMapping(virtualNodeId, actualNode);
        LogUtils.d(TAG, "Lifecycle: Added mapping for %s", virtualNodeId);

        // 2. 使用映射
        AccessibilityNodeInfoCompat retrievedNode = mappingManager.getActualNode(virtualNodeId);
        if (retrievedNode != null) {
            LogUtils.d(TAG, "Lifecycle: Successfully retrieved node");
            // 使用完后记得回收
            retrievedNode.recycle();
        }

        // 3. 检查节点是否仍然有效
        AccessibilityNodeInfoCompat checkNode = mappingManager.getActualNode(virtualNodeId);
        if (checkNode == null) {
            LogUtils.d(TAG, "Lifecycle: Node has become invalid, mapping automatically removed");
        } else {
            checkNode.recycle();
        }

        // 4. 手动清理（可选，在确定不再需要时）
        mappingManager.removeMappingByVirtualId(virtualNodeId);
        LogUtils.d(TAG, "Lifecycle: Manually removed mapping");
    }

    /**
     * 获取映射管理器实例
     * @return NodeMappingManager实例
     */
    public NodeMappingManager getMappingManager() {
        return mappingManager;
    }

    /**
     * 示例使用方法的完整流程
     * @param context 应用上下文
     * @param rootNode 根节点
     */
    public static void fullExampleUsage(Context context, AccessibilityNodeInfo rootNode) {
        LogUtils.d(TAG, "=== Starting Full Example Usage ===");
        
        // 创建示例实例
        NodeMappingExample example = new NodeMappingExample(context);
        
        // 构建虚拟树并建立映射
        JSONObject virtualTree = example.buildVirtualTreeWithMapping(rootNode);
        
        if (virtualTree != null) {
            LogUtils.d(TAG, "Virtual tree created successfully");
            
            // 如果需要处理特定节点
            if (rootNode != null) {
                AccessibilityNodeInfoCompat rootCompat = AccessibilityNodeInfoCompat.wrap(rootNode);
                
                // 查找虚拟ID
                String virtualId = example.findVirtualIdByActualNode(rootCompat);
                if (virtualId != null) {
                    // 通过虚拟ID反查实际节点
                    AccessibilityNodeInfoCompat foundNode = example.findActualNodeByVirtualId(virtualId);
                    if (foundNode != null) {
                        LogUtils.d(TAG, "Bidirectional mapping verification successful");
                        foundNode.recycle();
                    }
                }
            }
        }
        
        LogUtils.d(TAG, "=== Full Example Usage Completed ===");
    }
} 