package com.google.android.accessibility.utils;

import android.content.Context;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import com.google.android.libraries.accessibility.utils.log.LogUtils;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * 管理虚拟节点和实际节点之间双向映射关系的管理器类
 * 提供节点映射的创建、查询、更新、删除以及持久化存储功能
 */
public class NodeMappingManager {

    private static final String TAG = "NodeMappingManager";

    // 核心映射数据结构
    private final Map<String, AccessibilityNodeInfoCompat> virtualToActualNodeMap;
    // Keys share the owned copies in virtualToActualNodeMap. Native equals(), not a
    // property hash or provider label, distinguishes nodes (including hash collisions).
    private final Map<AccessibilityNodeInfoCompat, String> actualToVirtualNodeMap;
    private final Map<String, String> virtualToActualGlobalIdMap;
    
    // 文件日志管理
    private final FileLogger fileLogger;
    private final Context context;
    private boolean closed;
    
    // 会话信息
    private String currentUserId = "default_user";
    private String currentTaskId = "default_task";

    /**
     * 构造函数
     * @param context 应用上下文
     */
    public NodeMappingManager(Context context) {
        this.context = context;
        this.virtualToActualNodeMap = new HashMap<>();
        this.actualToVirtualNodeMap = new HashMap<>();
        this.virtualToActualGlobalIdMap = new HashMap<>();
        
        // 初始化FileLogger
        this.fileLogger = new FileLogger(context);
        
        // 设置基础日志目录为node_mappings
        File baseLogDir = new File(context.getExternalFilesDir(null), "screen_reader_logs/node_mappings");
        if (!baseLogDir.exists()) {
            if (!baseLogDir.mkdirs()) {
                LogUtils.e(TAG, "Failed to create node mappings log directory: " + baseLogDir.getAbsolutePath());
            }
        }
        this.fileLogger.setBaseLogDirectory(baseLogDir.getAbsolutePath());
        
        // 暂时不启用node_mapping_log日志类型
        // this.fileLogger.enableLogType("node_mapping_log");
        
        // 暂时不启用node_names_log日志类型
        // this.fileLogger.enableLogType("node_names_log");
        
        // 加载已有映射
        loadMappingsFromFile();
    }

    /**
     * 生成实际节点的持久化描述ID（属性回退值可能碰撞，不用于native身份查询）
     * @param node 实际节点
     * @return 描述ID，格式为"windowId_nodeId"
     */
    public static String generateActualNodeGlobalId(AccessibilityNodeInfoCompat node) {
        if (node == null) {
            return "null_null";
        }
        
        int windowId = node.getWindowId();
        String nodeId;
        
        // 优先使用getUniqueId() (API 30+)
        String uniqueId = node.getUniqueId();
        if (uniqueId != null && !uniqueId.isEmpty()) {
            nodeId = uniqueId;
        } else {
            // 回退到使用generateElementHashId
            AccessibilityNodeInfo nodeInfo = node.unwrap();
            if (nodeInfo != null) {
                nodeId = AccessibilityNodeInfoUtils.generateElementHashId(nodeInfo);
            } else {
                nodeId = "unknown_" + node.hashCode();
            }
        }
        
        return windowId + "_" + nodeId;
    }

    /**
     * 添加虚拟节点和实际节点的映射关系
     * @param virtualNodeId 虚拟节点ID
     * @param actualNode 实际节点
     */
    public synchronized void addMapping(String virtualNodeId, AccessibilityNodeInfoCompat actualNode) {
        if (closed) return;
        if (virtualNodeId == null || actualNode == null) {
            LogUtils.w(TAG, "Cannot add mapping with null virtualNodeId or actualNode");
            return;
        }
        
        String actualNodeGlobalId = generateActualNodeGlobalId(actualNode);
        
        AccessibilityNodeInfoCompat nodeCopy = AccessibilityNodeInfoCompat.obtain(actualNode);
        removeInvalidNode(virtualNodeId);
        virtualToActualNodeMap.put(virtualNodeId, nodeCopy);
        // HashMap.put keeps an equal old key object. Replace it explicitly so removing
        // an older capture cannot recycle the key owned by the newest reverse mapping.
        actualToVirtualNodeMap.remove(nodeCopy);
        actualToVirtualNodeMap.put(nodeCopy, virtualNodeId);
        virtualToActualGlobalIdMap.put(virtualNodeId, actualNodeGlobalId);
        
        // 保存到文件
        saveMappingsToFile();
        saveNodeNamesToFile();
    }

    /**
     * 通过虚拟节点ID获取实际节点
     * @param virtualNodeId 虚拟节点ID
     * @return 实际节点，如果不存在或已失效则返回null
     */
    public synchronized AccessibilityNodeInfoCompat getActualNode(String virtualNodeId) {
        if (virtualNodeId == null) {
            return null;
        }
        
        AccessibilityNodeInfoCompat cachedNode = virtualToActualNodeMap.get(virtualNodeId);
        if (cachedNode != null) {
            // 检查节点是否仍然有效
            if (cachedNode.refresh()) {
                return AccessibilityNodeInfoCompat.obtain(cachedNode);
            } else {
                // 节点已失效，移除映射（不触发保存）
                removeInvalidNode(virtualNodeId);
                return null;
            }
        }
        
        // 缓存中没有，尝试通过globalId查找
        String actualNodeGlobalId = virtualToActualGlobalIdMap.get(virtualNodeId);
        if (actualNodeGlobalId != null) {
            // 这里可以实现实时查找逻辑，但为了简化，暂时返回null
        }
        
        return null;
    }

    /**
     * 通过实际节点获取虚拟节点ID
     * @param actualNode 实际节点
     * @return 虚拟节点ID，如果不存在则返回null
     */
    public synchronized String getVirtualNodeId(AccessibilityNodeInfoCompat actualNode) {
        if (actualNode == null) {
            return null;
        }
        
        return actualToVirtualNodeMap.get(actualNode);
    }

    /**
     * 通过实际节点全局ID获取虚拟节点ID
     * @param actualNodeGlobalId 实际节点全局ID
     * @return 虚拟节点ID，如果不存在或描述ID对应多个映射则返回null
     */
    public synchronized String getVirtualNodeId(String actualNodeGlobalId) {
        if (actualNodeGlobalId == null) return null;
        String match = null;
        for (Map.Entry<String, String> entry : virtualToActualGlobalIdMap.entrySet()) {
            if (actualNodeGlobalId.equals(entry.getValue())) {
                if (match != null) return null;
                match = entry.getKey();
            }
        }
        return match;
    }

    /**
     * 通过虚拟节点ID移除映射关系
     * @param virtualNodeId 虚拟节点ID
     */
    public synchronized void removeMappingByVirtualId(String virtualNodeId) {
        if (virtualNodeId == null) {
            return;
        }
        
        removeInvalidNode(virtualNodeId);
        
        saveMappingsToFile();
        saveNodeNamesToFile();
    }
    
    /**
     * 移除失效节点（内部方法，不触发保存）
     * @param virtualNodeId 虚拟节点ID
     */
    private void removeInvalidNode(String virtualNodeId) {
        if (virtualNodeId == null) {
            return;
        }
        
        AccessibilityNodeInfoCompat node = virtualToActualNodeMap.remove(virtualNodeId);
        if (node != null) {
            // Remove before recycle(), which can reset the native identity/hash.
            actualToVirtualNodeMap.remove(node, virtualNodeId);
            node.recycle();
        }
        virtualToActualGlobalIdMap.remove(virtualNodeId);
        
        // 注意：不调用保存方法，避免递归
    }

    /**
     * 通过实际节点移除映射关系
     * @param actualNode 实际节点
     */
    public synchronized void removeMappingByActualNode(AccessibilityNodeInfoCompat actualNode) {
        if (actualNode == null) {
            return;
        }
        
        String virtualNodeId = actualToVirtualNodeMap.get(actualNode);
        removeInvalidNode(virtualNodeId);
        
        saveMappingsToFile();
        saveNodeNamesToFile();
    }

    /**
     * 清空所有映射关系
     */
    /** Service exit releases owned handles and rejects a retiring capture worker. */
    public synchronized void close() {
        closed = true;
        clearAllMappings();
    }

    public synchronized void clearAllMappings() {
        actualToVirtualNodeMap.clear();
        // 回收所有存储的节点
        for (AccessibilityNodeInfoCompat node : virtualToActualNodeMap.values()) {
            if (node != null) {
                node.recycle();
            }
        }
        
        virtualToActualNodeMap.clear();
        virtualToActualGlobalIdMap.clear();
        
        saveMappingsToFile();
        saveNodeNamesToFile();
    }

    /**
     * 设置会话信息
     * @param userId 用户ID
     * @param taskId 任务ID
     */
    public void setSessionInfo(String userId, String taskId) {
        this.currentUserId = userId != null ? userId : "default_user";
        this.currentTaskId = taskId != null ? taskId : "default_task";
        
        // 通知FileLogger更新会话目录
        fileLogger.initializeSessionDirectories(this.currentUserId, this.currentTaskId);
    }

    /**
     * 保存节点名字信息到文件
     */
    private void saveNodeNamesToFile() {
        try {
            JSONObject rootJson = new JSONObject();
            
            // 添加元数据
            String timestamp = new SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(new Date());
            rootJson.put("captureTimestamp", timestamp);
            rootJson.put("userId", currentUserId);
            rootJson.put("taskId", currentTaskId);
            
            // 创建节点名字数组
            JSONArray nodeNamesArray = new JSONArray();
            java.util.List<String> invalidNodes = new java.util.ArrayList<>();
            
            // 安全遍历，避免并发修改异常
            for (Map.Entry<String, AccessibilityNodeInfoCompat> entry : virtualToActualNodeMap.entrySet()) {
                String virtualNodeId = entry.getKey();
                AccessibilityNodeInfoCompat actualNode = entry.getValue();
                String actualNodeGlobalId = virtualToActualGlobalIdMap.get(virtualNodeId);
                
                JSONObject nodeNameEntry = new JSONObject();
                nodeNameEntry.put("virtualNodeId", virtualNodeId);
                nodeNameEntry.put("virtualNodeName", virtualNodeId);
                nodeNameEntry.put("actualNodeGlobalId", actualNodeGlobalId != null ? actualNodeGlobalId : "unknown");
                
                String actualNodeName = "[NODE_INVALID]";
                String retrievalStatus = "NODE_INVALID";
                
                if (actualNode != null) {
                    // 检查节点是否仍然有效，但不调用refresh()来避免副作用
                    try {
                        // 优先尝试获取文本内容
                        CharSequence text = actualNode.getText();
                        if (text != null && text.length() > 0) {
                            actualNodeName = text.toString();
                            retrievalStatus = "SUCCESS";
                        } else {
                            // 尝试获取内容描述
                            CharSequence contentDesc = actualNode.getContentDescription();
                            if (contentDesc != null && contentDesc.length() > 0) {
                                actualNodeName = contentDesc.toString();
                                retrievalStatus = "SUCCESS";
                            } else {
                                actualNodeName = "[NO_NAME_FOUND]";
                                retrievalStatus = "NAME_NOT_FOUND";
                            }
                        }
                    } catch (Exception e) {
                        // 节点可能已失效，标记为待删除
                        invalidNodes.add(virtualNodeId);
                        actualNodeName = "[NODE_ACCESS_ERROR]";
                        retrievalStatus = "ACCESS_ERROR";
                    }
                }
                
                nodeNameEntry.put("actualNodeName", actualNodeName);
                nodeNameEntry.put("retrievalStatus", retrievalStatus);
                nodeNamesArray.put(nodeNameEntry);
            }
            rootJson.put("node_names", nodeNamesArray);
            
            // 使用FileLogger保存
            String fileName = "node_names_log_" + currentUserId + "_" + currentTaskId + "_" + timestamp;
            fileLogger.logJson(fileName, rootJson);
            
            // 延迟删除失效节点，避免在遍历过程中修改map
            for (String invalidNodeId : invalidNodes) {
                removeInvalidNode(invalidNodeId);
            }
            
        } catch (JSONException e) {
            LogUtils.e(TAG, "Error saving node names to file: " + e.getMessage(), e);
        }
    }

    /**
     * 保存映射关系到文件
     */
    private void saveMappingsToFile() {
        try {
            JSONObject rootJson = new JSONObject();
            
            // 添加元数据
            String timestamp = new SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(new Date());
            rootJson.put("captureTimestamp", timestamp);
            rootJson.put("userId", currentUserId);
            rootJson.put("taskId", currentTaskId);
            
            // 创建映射数组
            JSONArray mappingsArray = new JSONArray();
            for (Map.Entry<String, String> entry : virtualToActualGlobalIdMap.entrySet()) {
                JSONObject mappingEntry = new JSONObject();
                mappingEntry.put("virtualNodeId", entry.getKey());
                mappingEntry.put("actualNodeGlobalId", entry.getValue());
                mappingsArray.put(mappingEntry);
            }
            rootJson.put("mappings", mappingsArray);
            
            // 使用FileLogger保存
            String fileName = "node_mappings_log_" + currentUserId + "_" + currentTaskId + "_" + timestamp;
            fileLogger.logJson(fileName, rootJson);
            
        } catch (JSONException e) {
            LogUtils.e(TAG, "Error saving mappings to file: " + e.getMessage(), e);
        }
    }

    /**
     * 从文件加载映射关系
     */
    private void loadMappingsFromFile() {
        try {
            // 获取正确的日志目录路径
            File userDir = new File(fileLogger.getBaseLogDirectory(), currentUserId);
            File taskDir = new File(userDir, currentTaskId);
            File logTypeDir = new File(taskDir, ""); // 使用FileLogger内部确定的类型目录名

            if (!logTypeDir.exists()) {
                return;
            }
            
            File[] files = logTypeDir.listFiles((dir, name) -> name.startsWith("node_mappings_log_") && name.endsWith(".json"));
            if (files == null || files.length == 0) {
                return;
            }
            
            // 找到最新的文件
            File latestFile = files[0];
            for (File file : files) {
                if (file.lastModified() > latestFile.lastModified()) {
                    latestFile = file;
                }
            }
            
            // 读取文件内容
            StringBuilder contentBuilder = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(new FileReader(latestFile))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    contentBuilder.append(line);
                }
            }
            
            if (contentBuilder.length() == 0) {
                return;
            }
            
            // 解析JSON
            JSONObject rootJson = new JSONObject(contentBuilder.toString());
            JSONArray mappingsArray = rootJson.optJSONArray("mappings");
            
            if (mappingsArray != null) {
                int loadedCount = 0;
                for (int i = 0; i < mappingsArray.length(); i++) {
                    JSONObject mappingEntry = mappingsArray.getJSONObject(i);
                    String virtualNodeId = mappingEntry.optString("virtualNodeId");
                    String actualNodeGlobalId = mappingEntry.optString("actualNodeGlobalId");
                    
                    if (!virtualNodeId.isEmpty() && !actualNodeGlobalId.isEmpty()) {
                        // Persisted labels cannot reconstruct live native node identity.
                        virtualToActualGlobalIdMap.put(virtualNodeId, actualNodeGlobalId);
                        loadedCount++;
                    }
                }
            }
            
        } catch (IOException | JSONException e) {
            LogUtils.e(TAG, "Error loading mappings from file: " + e.getMessage(), e);
        }
    }

    /**
     * 生成虚拟节点ID
     * @return 新的虚拟节点ID
     */
    public static String generateVirtualNodeId() {
        return UUID.randomUUID().toString();
    }
} 