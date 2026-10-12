package com.google.android.accessibility.utils;

import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import org.json.JSONObject;
import com.google.android.libraries.accessibility.utils.log.LogUtils;

/**
 * 焦点代理类
 * 负责拦截焦点决策并根据虚拟树中的isVirtualFocusNode属性做出判断
 */
public class FocusProxy {

    private static final String TAG = "FocusProxy";
    
    // 单例实例
    private static FocusProxy instance = null;
    
    // 节点映射管理器
    private final NodeMappingManager nodeMappingManager;
    
    // 虚拟树管理器
    private final VirtualTreeManager virtualTreeManager;

    /**
     * 私有构造函数
     * @param nodeMappingManager 节点映射管理器
     * @param virtualTreeManager 虚拟树管理器
     */
    private FocusProxy(NodeMappingManager nodeMappingManager, VirtualTreeManager virtualTreeManager) {
        this.nodeMappingManager = nodeMappingManager;
        this.virtualTreeManager = virtualTreeManager;
    }

    /**
     * 初始化焦点代理
     * @param nodeMappingManager 节点映射管理器
     * @param virtualTreeManager 虚拟树管理器
     */
    public static synchronized void initialize(NodeMappingManager nodeMappingManager, VirtualTreeManager virtualTreeManager) {
        if (instance == null) {
            instance = new FocusProxy(nodeMappingManager, virtualTreeManager);
            LogUtils.d(TAG, "FocusProxy initialized");
        }
    }

    /**
     * 获取焦点代理实例
     * @return FocusProxy实例，如果未初始化则返回null
     */
    public static synchronized FocusProxy getInstance() {
        return instance;
    }

    /**
     * 代理的shouldFocusNode方法
     * 根据虚拟树中的isVirtualFocusNode属性决定节点是否应该获得焦点
     * @param node 要检查的节点
     * @return 如果节点应该获得焦点返回true，否则返回false
     */
    public boolean shouldFocusNode(AccessibilityNodeInfoCompat node) {
        if (node == null) {
            LogUtils.v(TAG, "FocusProxy: Don't focus, node=null");
            return false;
        }

        synchronized (virtualTreeManager) {
        try {
            if (!virtualTreeManager.isFilteringActive()) {
                return AccessibilityNodeInfoUtils.shouldFocusNodeOriginal(node);
            }
            // 步骤1: 查找实际节点对应的虚拟ID
            String virtualId = nodeMappingManager.getVirtualNodeId(node);
            
            if (virtualId == null) {
                LogUtils.v(TAG, "FocusProxy: No virtual ID found for node, falling back to original logic");
                // 回退到原始的shouldFocusNode逻辑
                return AccessibilityNodeInfoUtils.shouldFocusNodeOriginal(node);
            }

            // 步骤2: 通过虚拟ID查找虚拟节点
            JSONObject virtualNode = virtualTreeManager.findNodeByVirtualId(virtualId);
            
            if (virtualNode == null) {
                LogUtils.v(TAG, "FocusProxy: Virtual node not found for ID: " + virtualId + ", falling back to original logic");
                // 回退到原始的shouldFocusNode逻辑
                return AccessibilityNodeInfoUtils.shouldFocusNodeOriginal(node);
            }

            // 步骤3: 读取isVirtualFocusNode属性
            boolean isVirtualFocusNode = virtualNode.optBoolean("isVirtualFocusNode", false);
            
            LogUtils.v(TAG, "FocusProxy: Virtual node " + virtualId + " isVirtualFocusNode=" + isVirtualFocusNode);
            return isVirtualFocusNode;
            
        } catch (Exception e) {
            LogUtils.e(TAG, "Error in FocusProxy.shouldFocusNode (" + e.getClass().getSimpleName() + ")");
            // 发生异常时回退到原始逻辑
            return AccessibilityNodeInfoUtils.shouldFocusNodeOriginal(node);
        }
    }

    }

    /**
     * 清理焦点代理
     */
    public static synchronized void cleanup() {
        if (instance != null) instance.nodeMappingManager.close();
        instance = null;
        LogUtils.d(TAG, "FocusProxy cleaned up");
    }
} 