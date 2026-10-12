package com.google.android.accessibility.utils;

import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import org.json.JSONObject;
import org.json.JSONArray;
import org.json.JSONException;
import com.google.android.libraries.accessibility.utils.log.LogUtils;

/**
 * 构建虚拟树结构的工具类
 * 用于创建与ui_elements_log格式一致的虚拟树日志，同时标记可聚焦节点
 */
public class VirtualTreeBuilder {

    private static final String TAG = "VirtualTreeBuilder";
    
    // 静态映射管理器实例，可选的，用于建立映射关系
    private static volatile NodeMappingManager mappingManager = null;

    /**
     * 设置映射管理器
     * @param manager 映射管理器实例
     */
    public static void setMappingManager(NodeMappingManager manager) {
        mappingManager = manager;
    }

    /**
     * 构建虚拟树结构的JSON表示，格式与ui_elements_log一致
     * @param rootNode 根节点
     * @return 虚拟树的JSON对象，如果根节点为空则返回null
     */
    public static JSONObject buildVirtualTree(AccessibilityNodeInfo rootNode) {
        return buildVirtualTree(rootNode, null, mappingManager);
    }

    public static JSONObject buildVirtualTree(AccessibilityNodeInfo rootNode, NativeTreeSnapshot observation) {
        return buildVirtualTree(rootNode, observation, mappingManager);
    }

    /** The capture's mapping owner is immutable for this complete recursion. */
    public static JSONObject buildVirtualTree(AccessibilityNodeInfo rootNode, NativeTreeSnapshot observation,
            NodeMappingManager mappingOwner) {
        if (rootNode == null) {
            return null;
        }

        try {
            JSONObject virtualRoot = buildVirtualNodeTree(rootNode, null, observation, null, 1, mappingOwner);
            if (virtualRoot != null) {
                virtualRoot.put("captureTimestamp", System.currentTimeMillis());
                if (observation != null) observation.seal();
                LogUtils.d(TAG, "Virtual tree built successfully with ui_elements_log format");
                return virtualRoot;
            }
        } catch (JSONException e) {
            LogUtils.e(TAG, "Error building virtual tree" + " (" + e.getClass().getSimpleName() + ")");
        }
        
        return null;
    }

    /**
     * 递归构建虚拟节点树，使用与ui_elements_log相同的格式
     * @param node 当前节点
     * @param virtualNodeId 虚拟节点ID，如果为null则自动生成
     * @return 虚拟节点的JSON对象
     */
    private static JSONObject buildVirtualNodeTree(AccessibilityNodeInfo node, String virtualNodeId,
            NativeTreeSnapshot observation, NativeTreeSnapshot.Entry parent, int depth, NodeMappingManager mappingOwner) {
        if (node == null) {
            return null;
        }

        try {
            JSONObject virtualNode = new JSONObject();
            
            // 生成或使用传入的虚拟节点ID
            if (virtualNodeId == null) {
                virtualNodeId = NodeMappingManager.generateVirtualNodeId();
            }
            
            // 如果有映射管理器，建立映射关系
            if (mappingOwner != null) {
                AccessibilityNodeInfoCompat nodeCompat = AccessibilityNodeInfoCompat.wrap(node);
                mappingOwner.addMapping(virtualNodeId, nodeCompat);
            }
            
            NodeProperties.write(node, virtualNode);
            NativeTreeSnapshot.Entry observed = observation == null ? null
                : observation.record(node, virtualNode, parent, depth);

            // 虚拟树特有属性 - 保留isVirtualFocusNode和虚拟节点ID
            boolean isVirtualFocusNode = isNodeAccessibilityFocusable(node);

            
            virtualNode.put("isVirtualFocusNode", isVirtualFocusNode);
            virtualNode.put("virtualNodeId", virtualNodeId);

            // 递归处理子节点 - 与ui_elements_log格式完全一致
            if (node.getChildCount() > 0) {
                JSONObject children = new JSONObject();
                for (int i = 0; i < node.getChildCount(); i++) {
                    AccessibilityNodeInfo child = node.getChild(i);
                    if (child != null) {
                        try {
                            // 生成子节点的虚拟ID
                            String childVirtualId = NodeMappingManager.generateVirtualNodeId();
                            JSONObject childJson = buildVirtualNodeTree(child, childVirtualId, observation, observed, depth + 1, mappingOwner);
                            if (childJson != null) {
                                // 使用与ui_elements_log相同的唯一ID生成方法
                                String elementId = AccessibilityNodeInfoUtils.generateUniqueElementId();
                                children.put(elementId, childJson);
                            }
                        } finally {
                            child.recycle();
                        }
                    }
                }
                virtualNode.put("children", children);
            }
            
            return virtualNode;
            
        } catch (JSONException e) {
            LogUtils.e(TAG, "Error building virtual node" + " (" + e.getClass().getSimpleName() + ")");
            return null;
        }
    }

    /**
     * 判断节点是否为可访问性聚焦的节点
     * @param node 要检查的节点
     * @return 如果节点可聚焦返回true，否则返回false
     */
    private static boolean isNodeAccessibilityFocusable(AccessibilityNodeInfo node) {
        if (node == null) {
            return false;
        }

        // 检查节点是否可见
        if (!node.isVisibleToUser()) {
            return false;
        }

        // 检查节点是否可聚焦或可点击
        if (node.isFocusable() || node.isClickable()) {
            return true;
        }

        // 检查是否为顶级滚动项目且有内容
        if (isTopLevelScrollItem(node) && hasValidContent(node)) {
            return true;
        }

        return false;
    }

    /**
     * 检查是否为顶级滚动项目
     * @param node 要检查的节点
     * @return 如果是顶级滚动项目返回true
     */
    private static boolean isTopLevelScrollItem(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo parent = node.getParent();
        if (parent == null) {
            return false;
        }

        try {
            // 检查父节点是否为可滚动容器
            String parentClass = parent.getClassName() != null ? parent.getClassName().toString() : "";
            return parentClass.contains("ListView") || 
                   parentClass.contains("RecyclerView") || 
                   parentClass.contains("ScrollView") ||
                   parentClass.contains("GridView");
        } finally {
            parent.recycle();
        }
    }

    /**
     * 检查节点是否有有效内容
     * @param node 要检查的节点
     * @return 如果有有效内容返回true
     */
    private static boolean hasValidContent(AccessibilityNodeInfo node) {
        if (node.getText() != null && node.getText().length() > 0) {
            return true;
        }
        
        if (node.getContentDescription() != null && node.getContentDescription().length() > 0) {
            return true;
        }

        // 检查子节点是否有内容
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                try {
                    if (hasValidContent(child)) {
                        return true;
                    }
                } finally {
                    child.recycle();
                }
            }
        }

        return false;
    }


}
