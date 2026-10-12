package com.google.android.accessibility.utils;

import org.json.JSONObject;
import org.json.JSONException;
import com.google.android.libraries.accessibility.utils.log.LogUtils;
import java.util.Iterator;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * 虚拟树管理器
 * 负责在内存中维护虚拟树的状态，并提供查询功能
 */
public class VirtualTreeManager {

    private static final String TAG = "VirtualTreeManager";
    
    // 单例实例
    private static VirtualTreeManager instance = null;
    
    // 当前虚拟树的根节点
    private JSONObject virtualTreeRoot;
    // Private defensive copy of the last local capture; remote updates never replace it.
    private JSONObject capturedTreeRoot;
    private SnapshotContext currentContext;
    private String activeRequest;
    private String baseRequest;
    private boolean filteringActive;
    private boolean paused;
    private NativeTreeSnapshot nativeSnapshot;

    public synchronized boolean isPaused() { return paused; }

    synchronized void setPaused(boolean value) {
        paused = value;
        withdrawFiltering();
    }

    synchronized void withdrawFiltering() {
        filteringActive = false;
        baseRequest = null;
    }

    public synchronized boolean hasCapture() { return !paused && capturedTreeRoot != null; }


    public synchronized void invalidate(SnapshotContext context) {
        currentContext = context;
        activeRequest = null;
        baseRequest = null;
        clearVirtualTree();
    }

    public synchronized boolean isCurrent(SnapshotContext context) {
        return context != null && context.equals(currentContext);
    }

    public synchronized boolean registerRequest(SnapshotContext context, String requestId, boolean talk) {
        if (paused || !isCurrent(context) || capturedTreeRoot == null || activeRequest != null || (talk && baseRequest == null)) return false;
        activeRequest = requestId;
        if (!talk) baseRequest = null;
        return true;
    }

    public synchronized boolean ownsRequest(SnapshotContext context, String requestId) {
        return !paused && isCurrent(context) && requestId != null && requestId.equals(activeRequest);
    }

    public synchronized boolean isFilteringActive() { return !paused && filteringActive; }

    public synchronized String baseRequest() { return baseRequest; }

    public synchronized void finishRequest(SnapshotContext context, String requestId, boolean decision) {
        if (ownsRequest(context, requestId)) {
            activeRequest = null;
            if (decision) baseRequest = requestId;
        }
    }

    
    // FileLogger实例，用于保存PC更新的虚拟树
    private FileLogger fileLogger;

    /**
     * 私有构造函数
     */
    private VirtualTreeManager() {
        this.virtualTreeRoot = null;
        this.fileLogger = null;
    }

    /**
     * 获取单例实例
     * @return VirtualTreeManager实例
     */
    public static synchronized VirtualTreeManager getInstance() {
        if (instance == null) {
            instance = new VirtualTreeManager();
        }
        return instance;
    }
    
    /**
     * 设置FileLogger实例，用于保存PC更新的虚拟树
     * @param logger FileLogger实例
     */
    public synchronized void setFileLogger(FileLogger logger) {
        this.fileLogger = logger;
    }

    /** Publish a local capture, keeping the source separate from the filtered display. */
    public synchronized boolean captureVirtualTree(SnapshotContext context, JSONObject newTree) {
        return captureVirtualTree(context, newTree, null);
    }

    public synchronized boolean captureVirtualTree(SnapshotContext context, JSONObject newTree, NativeTreeSnapshot evidence) {
        if (paused || !isCurrent(context)) return false;
        try {
            JSONObject captured = VirtualTreeValidator.capture(newTree);
            JSONObject display = VirtualTreeValidator.copyTree(captured);
            capturedTreeRoot = captured;
            virtualTreeRoot = display;
            if (nativeSnapshot != null) nativeSnapshot.close();
            nativeSnapshot = evidence;
            withdrawFiltering();
            return true;
        } catch (IllegalArgumentException | JSONException e) {
            withdrawFiltering();
            LogUtils.w(TAG, "Local virtual tree rejected");
            return false;
        }
    }

    synchronized boolean unchangedContent(android.view.accessibility.AccessibilityEvent event) {
        return !paused && capturedTreeRoot != null && nativeSnapshot != null && nativeSnapshot.unchanged(event);
    }

    /** Validate the whole response under the same lock as the final state commit. */
    public synchronized boolean applyFilteredVirtualTree(SnapshotContext context, String requestId, JSONObject candidate) {
        if (!ownsRequest(context, requestId)) return false;
        try {
            JSONObject validated = VirtualTreeValidator.filtered(capturedTreeRoot, candidate);
            virtualTreeRoot = validated;
            filteringActive = VirtualTreeValidator.inspectNodes(validated) > 0;
            savePcUpdatedVirtualTree(validated);
            return true;
        } catch (IllegalArgumentException | JSONException e) {
            withdrawFiltering();
            LogUtils.w(TAG, "PC virtual tree rejected");
            return false;
        }
    }

    /** Callers cannot mutate the display or captured source through returned JSON. */
    public synchronized JSONObject getVirtualTreeRoot() {
        return copyForRead(virtualTreeRoot);
    }

    /**
     * 根据虚拟节点ID查找对应的虚拟节点
     * @param virtualId 虚拟节点ID
     * @return 匹配的虚拟节点JSON对象，如果未找到则返回null
     */
    public synchronized JSONObject findNodeByVirtualId(String virtualId) {
        if (virtualTreeRoot == null || virtualId == null) {
            return null;
        }
        
        JSONObject node = findNodeByVirtualIdRecursive(virtualTreeRoot, virtualId);
        return copyForRead(node);
    }

    private JSONObject copyForRead(JSONObject tree) {
        if (tree == null) return null;
        try {
            return VirtualTreeValidator.copyTree(tree);
        } catch (JSONException e) {
            throw new IllegalStateException("Cannot copy validated virtual tree");
        }
    }

    /**
     * 递归搜索虚拟节点
     * @param currentNode 当前搜索的节点
     * @param targetVirtualId 目标虚拟节点ID
     * @return 匹配的虚拟节点，如果未找到则返回null
     */
    private JSONObject findNodeByVirtualIdRecursive(JSONObject currentNode, String targetVirtualId) {
        if (currentNode == null) {
            return null;
        }
        
        try {
            // 检查当前节点是否匹配
            String currentVirtualId = currentNode.optString("virtualNodeId", null);
            if (targetVirtualId.equals(currentVirtualId)) {
                return currentNode;
            }
            
            // 递归搜索子节点
            JSONObject children = currentNode.optJSONObject("children");
            if (children != null) {
                Iterator<String> keys = children.keys();
                while (keys.hasNext()) {
                    String key = keys.next();
                    JSONObject child = children.optJSONObject(key);
                    if (child != null) {
                        JSONObject result = findNodeByVirtualIdRecursive(child, targetVirtualId);
                        if (result != null) {
                            return result;
                        }
                    }
                }
            }
        } catch (Exception e) {
            LogUtils.e(TAG, "Error searching for virtual node" + " (" + e.getClass().getSimpleName() + ")");
        }
        
        return null;
    }

    /**
     * 清空虚拟树
     */
    public synchronized void clearVirtualTree() {
        if (nativeSnapshot != null) nativeSnapshot.close();
        nativeSnapshot = null;
        this.virtualTreeRoot = null;
        this.capturedTreeRoot = null;
        this.filteringActive = false;
        this.activeRequest = null;
        this.baseRequest = null;
        LogUtils.d(TAG, "Virtual tree cleared from memory");
    }

    /**
     * 保存PC端返回的更新虚拟树到专门的文件夹
     * @param pcUpdatedTree PC端返回的更新虚拟树
     */
    private void savePcUpdatedVirtualTree(JSONObject pcUpdatedTree) {
        if (pcUpdatedTree == null) {
            LogUtils.w(TAG, "PC更新的虚拟树为空，跳过保存");
            return;
        }
        
        if (fileLogger == null || !fileLogger.isLogTypeEnabled("pc_updated_virtual_tree_logs")) {
            // Persistence requires explicit opt-in; updating the in-memory tree is unaffected.
            return;
        }
        
        try {
            // 创建包装对象，添加保存时间戳
            JSONObject wrappedTree = new JSONObject();
            String saveTimestamp = new SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(new Date());
            wrappedTree.put("saveTimestamp", saveTimestamp);
            wrappedTree.put("pcUpdatedTree", pcUpdatedTree);
            wrappedTree.put("saveTimeMillis", System.currentTimeMillis());
            
            // 保存到pc_updated_virtual_tree_logs文件夹
            fileLogger.logJson("pc_updated_virtual_tree_log", wrappedTree);
            LogUtils.d(TAG, "PC更新的虚拟树已保存到文件，时间戳: " + saveTimestamp);
            
        } catch (JSONException e) {
            LogUtils.e(TAG, "保存PC更新虚拟树时发生JSON错误" + " (" + e.getClass().getSimpleName() + ")");
        } catch (Exception e) {
            LogUtils.e(TAG, "保存PC更新虚拟树时发生错误" + " (" + e.getClass().getSimpleName() + ")");
        }
    }
}
