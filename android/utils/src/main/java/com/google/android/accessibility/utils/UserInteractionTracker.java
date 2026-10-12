package com.google.android.accessibility.utils;

import android.content.Context;
import android.graphics.Rect;
import android.view.accessibility.AccessibilityNodeInfo;
import android.util.Log;

import org.json.JSONObject;
import org.json.JSONArray;
import org.json.JSONException;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;
import java.io.File;
import java.io.FileWriter;
import java.io.BufferedWriter;
import java.io.IOException;

import com.google.android.libraries.accessibility.utils.log.LogUtils;

/**
 * UserInteractionTracker类用于跟踪用户与UI元素的交互
 * 实时记录用户的导航路径、停留时长等交互行为
 * 
 * 已按照参考代码修改，主要变更：
 * 1. 添加了新的 logUIInteraction(AccessibilityNodeInfo) 方法，实现与参考代码一致的数据结构
 * 2. 修改了 recordInteraction 方法，使用新的 logUIInteraction 方法
 * 3. 实现了与参考代码一致的访问记录结构，包括 visitRecords 和 navigationPath
 * 4. 添加了 lastVisitedElement 和 visitStartTime 变量，用于跟踪元素访问
 * 5. 修改了 saveInteractionsToFile 方法，使用与参考代码一致的数据格式
 * 6. 修改了 endSession 方法，确保最后一个元素的访问记录被正确更新
 */
public class UserInteractionTracker {

    private static final String TAG = "UserInteractionTracker";
    
    private Context context;
    private FileLogger fileLogger;
    private String userId;
    private String taskId;
    private long sessionStartTime;
    
    // 当前交互状态跟踪
    private String currentElementId;
    private long currentElementStartTime;
    private int totalInteractionCount;

    // Stores interactions per window. Key: windowId, Value: JSONObject of interactions in that window
    private Map<String, JSONObject> windowInteractions = new HashMap<>();
    private String lastInteractedElementId = null;
    private long lastInteractionTime = 0;

    // 新增：用于跟踪访问记录的变量，与参考代码保持一致
    private String lastVisitedElement = null;
    private long visitStartTime = 0;

    private static final SimpleDateFormat ISO8601_FORMAT = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);

    // 交互类型常量
    public static final String INTERACTION_CLICK = "CLICK";
    public static final String INTERACTION_FOCUS = "FOCUS";
    public static final String INTERACTION_LONG_CLICK = "LONG_CLICK";
    public static final String INTERACTION_SCROLL = "SCROLL";
    public static final String INTERACTION_TEXT_CHANGE = "TEXT_CHANGE";
    public static final String INTERACTION_DOUBLE_TAP = "DOUBLE_TAP";
    public static final String INTERACTION_SWIPE = "SWIPE";

    static {
        ISO8601_FORMAT.setTimeZone(TimeZone.getTimeZone("UTC"));
    }

    public UserInteractionTracker(Context context, FileLogger fileLogger) {
        this.context = context;
        this.fileLogger = fileLogger;
        this.sessionStartTime = System.currentTimeMillis();
        this.totalInteractionCount = 0;
        
        LogUtils.i(TAG, "UserInteractionTracker已初始化");
    }

    /**
     * 设置会话信息并创建交互日志文件
     * @param userId 用户ID
     * @param taskId 任务ID
     */
    public void setSessionInfo(String userId, String taskId) {
        this.userId = userId;
        this.taskId = taskId;
        this.sessionStartTime = System.currentTimeMillis();
        
        // 确保FileLogger已初始化
        if (fileLogger != null) {
            // 设置FileLogger的会话信息，这会初始化所有日志目录和文件
            fileLogger.initializeSessionDirectories(userId, taskId);
            
            LogUtils.i(TAG, "会话信息已设置 - 用户ID: %s, 任务ID: %s", userId, taskId);
        } else {
            LogUtils.e(TAG, "FileLogger未初始化，无法设置会话信息");
        }
    }

    /**
     * 获取设备信息
     */
    private JSONObject getDeviceInfo() throws JSONException {
        JSONObject deviceInfo = new JSONObject();
        deviceInfo.put("model", android.os.Build.MODEL);
        deviceInfo.put("manufacturer", android.os.Build.MANUFACTURER);
        deviceInfo.put("version", android.os.Build.VERSION.RELEASE);
        deviceInfo.put("sdk", android.os.Build.VERSION.SDK_INT);
        return deviceInfo;
    }

    /**
     * 获取应用版本信息
     */
    private String getAppVersion() {
        try {
            return context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "unknown";
        }
    }

    /**
     * 记录UI交互行为
     * @param elementInfo UI元素信息
     * @param interactionType 交互类型（如"focus", "click", "scroll"等）
     * @param additionalData 额外数据
     */
    public void logUIInteraction(String elementInfo, String interactionType, JSONObject additionalData) {
        // 这个方法保留用于兼容性，但不再直接记录到文件
        // 实际的记录通过 logUIInteraction(AccessibilityNodeInfo node) 方法进行
        LogUtils.d(TAG, "记录UI交互 - 类型: %s, 元素: %s", interactionType, elementInfo);
    }

    /**
     * 记录元素聚焦事件
     * @param elementInfo 元素信息
     * @param elementClass 元素类名
     * @param elementText 元素文本
     */
    public void logElementFocus(String elementInfo, String elementClass, String elementText) {
        LogUtils.d(TAG, "记录元素聚焦 - 元素: %s", elementInfo);
    }

    /**
     * 记录元素点击事件
     * @param elementInfo 元素信息
     * @param clickType 点击类型（如"single", "double", "long"）
     */
    public void logElementClick(String elementInfo, String clickType) {
        LogUtils.d(TAG, "记录元素点击 - 元素: %s, 类型: %s", elementInfo, clickType);
    }

    /**
     * 记录滚动事件
     * @param direction 滚动方向
     * @param distance 滚动距离
     */
    public void logScrollAction(String direction, int distance) {
        LogUtils.d(TAG, "记录滚动事件 - 方向: %s, 距离: %d", direction, distance);
    }

    /**
     * 记录导航事件
     * @param navigationType 导航类型（如"swipe_right", "swipe_left", "explore_by_touch"）
     * @param fromElement 起始元素
     * @param toElement 目标元素
     */
    public void logNavigationAction(String navigationType, String fromElement, String toElement) {
        LogUtils.d(TAG, "记录导航事件 - 类型: %s, 从: %s, 到: %s", navigationType, fromElement, toElement);
    }

    /**
     * 获取当前会话的统计信息
     */
    public JSONObject getSessionStatistics() {
        try {
            JSONObject stats = new JSONObject();
            stats.put("totalInteractions", totalInteractionCount);
            stats.put("sessionDuration", System.currentTimeMillis() - sessionStartTime);
            stats.put("interactionRate", totalInteractionCount > 0 ? 
                    (System.currentTimeMillis() - sessionStartTime) / totalInteractionCount : 0);
            return stats;
        } catch (JSONException e) {
            LogUtils.e(TAG, "获取会话统计时出错: " + e.getMessage(), e);
            return new JSONObject();
        }
    }

    /**
     * 结束当前会话，记录会话结束信息
     */
    public void endSession() {
        if (fileLogger == null || !fileLogger.isLogTypeEnabled("ui_interaction_logs")) {
            return;
        }
        
        try {
            // 更新最后访问元素的记录
            if (lastVisitedElement != null) {
                updateLastVisitRecordDuration(windowInteractions, lastVisitedElement, System.currentTimeMillis());
            }

            // 保存所有交互数据（这将创建最终的正确格式）
            saveInteractionsToFile();
            
            LogUtils.i(TAG, "会话结束信息已记录 - 会话持续时间: %d ms, 交互总数: %d", 
                    System.currentTimeMillis() - sessionStartTime, totalInteractionCount);
            
            // 清理资源
            windowInteractions.clear();
            lastVisitedElement = null;
            visitStartTime = 0;
            
        } catch (Exception e) {
            LogUtils.e(TAG, "记录会话结束信息时出错: " + e.getMessage(), e);
        }
    }

    /**
     * Records an interaction with an AccessibilityNodeInfo.
     * This method follows the reference code format with visitRecords structure.
     *
     * @param node            The AccessibilityNodeInfo with which the user interacted.
     * @param interactionType A string describing the type of interaction (e.g., "CLICK", "FOCUS").
     */
    public void recordInteraction(AccessibilityNodeInfo node, String interactionType) {
        if (node == null) {
            Log.w(TAG, "Attempted to record interaction with a null node.");
            return;
        }
        
        // 使用新的 logUIInteraction 方法记录交互
        logUIInteraction(node);
    }

    /**
     * Logs the interaction with a specific UI element.
     * Captures details like element name, text, position, and visit records.
     * @param node The AccessibilityNodeInfo representing the interacted element.
     */
    public void logUIInteraction(AccessibilityNodeInfo node) {
        if (node == null) {
            Log.w(TAG, "Attempted to log UI interaction with a null node.");
            return;
        }

        if (fileLogger == null || !fileLogger.isLogTypeEnabled("ui_interaction_logs")) {
            return; // 如果交互日志未启用，则不记录
        }

        try {
            String windowId = getCurrentWindowId(node);
            String windowName = getCurrentWindowName(node);
            Rect nodeBounds = new Rect();
            node.getBoundsInScreen(nodeBounds);
            int centerX = nodeBounds.centerX();
            int centerY = nodeBounds.centerY();

            // Generate a unique ID for the element using the new hash-based method
            String elementId = generateElementHashId(node);

            // Retrieve or create interaction records for the current window.
            JSONObject windowData = windowInteractions.get(windowId);
            if (windowData == null) {
                windowData = new JSONObject();
                windowData.put("windowName", windowName);
                windowInteractions.put(windowId, windowData);
            }
            
            JSONObject elementInteraction = windowData.optJSONObject(elementId);
            if (elementInteraction == null) {
                elementInteraction = new JSONObject();
            }

            // Populate element details.
            elementInteraction.put("name", getNodeDescriptionAll(node)); // Comprehensive name
            elementInteraction.put("text", getSafeString(node.getText()));
            elementInteraction.put("contentDescription", getSafeString(node.getContentDescription()));

            // If text and contentDescription are empty, try to find a description from children.
            if ((node.getText() == null || node.getText().toString().trim().isEmpty()) && 
                (node.getContentDescription() == null || node.getContentDescription().toString().trim().isEmpty())) {
                String childDescription = findCombinedChildDescription(node);
                if (childDescription != null) {
                    elementInteraction.put("childName", childDescription);
                }
            }

            elementInteraction.put("position", new JSONObject().put("x", centerX).put("y", centerY));

            // Update visit records for the element.
            JSONArray visitRecords = elementInteraction.optJSONArray("visitRecords");
            if (visitRecords == null) {
                visitRecords = new JSONArray();
            }
            
            long currentTime = System.currentTimeMillis();

            if (lastVisitedElement != null && !lastVisitedElement.equals(elementId)) {
                // Finalize the previous element's visit record if applicable.
                updateLastVisitRecordDuration(windowInteractions, lastVisitedElement, currentTime);
            }

            if (!elementId.equals(lastVisitedElement)) {
                // Start a new visit record for the current element.
                JSONObject newVisit = new JSONObject();
                newVisit.put("startTime", ISO8601_FORMAT.format(new Date(currentTime)));
                
                JSONArray navigationPath = new JSONArray();
                JSONObject navSegment = new JSONObject();
                navSegment.put("previousElement", lastVisitedElement != null ? lastVisitedElement : "null");
                navSegment.put("currentElement", elementId);
                navSegment.put("timeSpentOnPrevious", lastVisitedElement != null ? currentTime - visitStartTime : 0);
                navigationPath.put(navSegment);
                
                newVisit.put("navigationPath", navigationPath);
                visitRecords.put(newVisit);
                
                visitStartTime = currentTime; // Reset visit start time for the new element.
            }

            elementInteraction.put("visitRecords", visitRecords);
            windowData.put(elementId, elementInteraction);
            
            // windowInteractions map is updated by reference.
            lastVisitedElement = elementId; // Update the last visited element.
            
            // 增加交互计数
            totalInteractionCount++;
            
            // 实时保存当前交互数据到文件（只保存当前元素，避免重复）
            saveSingleInteraction(windowId, windowName, elementId, elementInteraction);
            
            Log.d(TAG, "UI interaction logged for element: " + elementId);
        } catch (JSONException e) {
            Log.e(TAG, "Error logging UI interaction: " + e.getMessage(), e);
        }
    }

    /**
     * 保存单个交互元素到文件，避免重复写入所有历史数据
     * @param windowId 窗口ID
     * @param windowName 窗口名称
     * @param elementId 元素ID
     * @param elementInteraction 元素交互数据
     */
    private void saveSingleInteraction(String windowId, String windowName, String elementId, JSONObject elementInteraction) {
        if (fileLogger == null) {
            Log.e(TAG, "FileLogger is not initialized. Cannot save single interaction.");
            return;
        }

        try {
            // 创建单个交互记录的数据结构
            JSONObject singleInteractionJson = new JSONObject();
            singleInteractionJson.put("userId", this.userId != null ? this.userId : "unknown");
            singleInteractionJson.put("taskId", this.taskId != null ? this.taskId : "unknown");
            singleInteractionJson.put("timestamp", ISO8601_FORMAT.format(new Date()));
            singleInteractionJson.put("totalInteractionCount", totalInteractionCount);
            
            // 创建当前交互的数据结构
            JSONObject interactionsJson = new JSONObject();
            JSONObject windowObject = new JSONObject();
            windowObject.put("windowName", windowName);
            
            JSONObject elements = new JSONObject();
            elements.put(elementId, elementInteraction);
            windowObject.put("elements", elements);
            
            interactionsJson.put(windowId, windowObject);
            singleInteractionJson.put("interactions", interactionsJson);
            
            // 使用FileLogger保存单个交互记录
            fileLogger.logOrUpdateUiInteraction(singleInteractionJson);
            
            Log.d(TAG, "Single UI interaction saved for element: " + elementId + " in window: " + windowId);
            
        } catch (JSONException e) {
            Log.e(TAG, "Error creating JSON for single interaction: " + e.getMessage(), e);
        }
    }

    /**
     * Updates the duration of the last visit record for a specific UI element.
     * @param windowInteractionsMap Map of window interactions.
     * @param elementId Identifier of the element whose last visit record needs updating.
     * @param endTime The timestamp marking the end of the visit.
     */
    private void updateLastVisitRecordDuration(Map<String, JSONObject> windowInteractionsMap, String elementId, long endTime) {
        try {
            // Find the element across all windows
            for (JSONObject windowData : windowInteractionsMap.values()) {
                JSONObject elementInteraction = windowData.optJSONObject(elementId);
                if (elementInteraction != null) {
                    JSONArray visitRecords = elementInteraction.optJSONArray("visitRecords");
                    if (visitRecords != null && visitRecords.length() > 0) {
                        JSONObject lastVisit = visitRecords.optJSONObject(visitRecords.length() - 1);
                        if (lastVisit != null) {
                            lastVisit.put("endTime", ISO8601_FORMAT.format(new Date(endTime)));
                            
                            // Update timeSpent in the navigation path of the last visit
                            JSONArray navigationPath = lastVisit.optJSONArray("navigationPath");
                            if (navigationPath != null && navigationPath.length() > 0) {
                                JSONObject lastNavSegment = navigationPath.optJSONObject(navigationPath.length() - 1);
                                if (lastNavSegment != null) {
                                    lastNavSegment.put("timeSpentOnCurrent", endTime - visitStartTime);
                                }
                            }
                            
                            // 计算并添加总停留时间
                            long startTime = 0;
                            try {
                                Date startDate = ISO8601_FORMAT.parse(lastVisit.getString("startTime"));
                                if (startDate != null) {
                                    startTime = startDate.getTime();
                                    long dwellTime = endTime - startTime;
                                    lastVisit.put("dwellTime", dwellTime);
                                }
                            } catch (Exception e) {
                                Log.e(TAG, "Error parsing start time: " + e.getMessage(), e);
                            }
                        }
                    }
                    return; // Found and updated the element
                }
            }
        } catch (JSONException e) {
            Log.e(TAG, "Error updating last visit record duration: " + e.getMessage(), e);
        }
    }

    /**
     * Gets a comprehensive string representation of a node, for logging or ID generation.
     * Includes text, content description, view ID resource name, and class name.
     * Implementation matches the reference Kotlin code but using Java constructs.
     */
    private String getNodeDescriptionAll(AccessibilityNodeInfo node) {
        StringBuilder description = new StringBuilder();
        
        if (node.getText() != null && !node.getText().toString().trim().isEmpty()) {
            description.append(node.getText().toString());
        }
        
        if (node.getContentDescription() != null && !node.getContentDescription().toString().trim().isEmpty()) {
            if (description.length() > 0) description.append(" | ");
            description.append(node.getContentDescription().toString());
        }
        
        if (node.getViewIdResourceName() != null) {
            if (description.length() > 0) description.append(" | ");
            description.append(node.getViewIdResourceName());
        }
        
        if (node.getClassName() != null) {
            if (description.length() > 0) description.append(" | ");
            description.append(node.getClassName().toString());
        }
        
        return description.length() > 0 ? description.toString() : "Unnamed element";
    }

    /**
     * Recursively finds a combined description from the direct children of a node.
     * Useful when a parent node has no direct text or content description.
     * Implementation matches the reference Kotlin code but using Java constructs.
     */
    private String findCombinedChildDescription(AccessibilityNodeInfo parentNode) {
        StringBuilder childDescriptions = new StringBuilder();
        
        for (int i = 0; i < parentNode.getChildCount(); i++) {
            AccessibilityNodeInfo child = parentNode.getChild(i);
            if (child != null) {
                try {
                    String desc = null;
                    if (child.getText() != null && !child.getText().toString().trim().isEmpty()) {
                        desc = child.getText().toString();
                    } else if (child.getContentDescription() != null && !child.getContentDescription().toString().trim().isEmpty()) {
                        desc = child.getContentDescription().toString();
                    }
                    
                    if (desc != null && !desc.trim().isEmpty()) {
                        if (childDescriptions.length() > 0) {
                            childDescriptions.append(", ");
                        }
                        childDescriptions.append(desc);
                    }
                } finally {
                    child.recycle();
                }
            }
        }
        
        return childDescriptions.length() > 0 ? childDescriptions.toString() : null;
    }

    /**
     * Gets the current window name from the node.
     */
    private String getCurrentWindowName(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo rootNode = null;
        try {
            // Try to get root from the node's window
            AccessibilityNodeInfo currentNode = node;
            while (currentNode != null) {
                AccessibilityNodeInfo parent = currentNode.getParent();
                if (parent == null) {
                    rootNode = currentNode;
                    break;
                }
                if (currentNode != node) { // Don't recycle the original node
                    currentNode.recycle();
                }
                currentNode = parent;
            }
            
            if (rootNode != null && rootNode.getClassName() != null) {
                return rootNode.getClassName().toString();
            }
        } catch (Exception e) {
            Log.e(TAG, "Error getting window name: " + e.getMessage(), e);
        } finally {
            if (rootNode != null && rootNode != node) {
                rootNode.recycle();
            }
        }
        return "unknown";
    }

    /**
     * 记录滑动交互
     * 
     * @param node 相关的节点
     * @param direction 滑动方向（例如："UP", "DOWN", "LEFT", "RIGHT"）
     */
    public void recordScrollInteraction(AccessibilityNodeInfo node, String direction) {
        if (node == null) {
            Log.w(TAG, "Attempted to record scroll interaction with a null node.");
            return;
        }
        
        // 首先记录基本的UI交互
        logUIInteraction(node);
        
        Log.d(TAG, "Scroll interaction recorded - Direction: " + direction);
    }
    
    /**
     * 记录文本变化交互
     * 
     * @param node 相关的节点
     * @param beforeText 变化前的文本
     * @param afterText 变化后的文本
     */
    public void recordTextChangeInteraction(AccessibilityNodeInfo node, 
                                            CharSequence beforeText, 
                                            CharSequence afterText) {
        if (node == null) {
            Log.w(TAG, "Attempted to record text change interaction with a null node.");
            return;
        }
        
        // 首先记录基本的UI交互
        logUIInteraction(node);
        
        Log.d(TAG, "Text change interaction recorded");
    }
    
    /**
     * Records UI interaction specifically after a double-tap gesture.
     * This method should be called only after double-tap operations.
     * 
     * @param node The AccessibilityNodeInfo that was double-tapped.
     */
    public void recordDoubleTapInteraction(AccessibilityNodeInfo node) {
        if (node == null) {
            Log.w(TAG, "Attempted to record double-tap interaction with a null node.");
            return;
        }
        
        // 使用统一的方式记录双击交互
        logUIInteraction(node);
        Log.d(TAG, "Double-tap interaction recorded");
    }

    /**
     * Records UI interaction specifically after a double-tap gesture with element information.
     * This is an alternative method that accepts element info directly.
     * 
     * @param elementInfo String description of the element that was double-tapped.
     */
    public void recordDoubleTapInteraction(String elementInfo) {
        if (elementInfo == null || elementInfo.trim().isEmpty()) {
            Log.w(TAG, "Attempted to record double-tap interaction with empty element info.");
            return;
        }
        
        Log.d(TAG, "Double-tap interaction recorded");
    }

    /**
     * Saves all currently tracked interactions for the session to a file.
     */
    public void saveInteractionsToFile() {
        if (fileLogger == null) {
            Log.e(TAG, "FileLogger is not initialized. Cannot save interactions.");
            return;
        }
        if (windowInteractions.isEmpty()) {
            Log.d(TAG, "No interactions to save.");
            return;
        }

        try {
            // 创建完整的会话数据
            JSONObject rootJson = new JSONObject();
            rootJson.put("userId", this.userId != null ? this.userId : "unknown");
            rootJson.put("taskId", this.taskId != null ? this.taskId : "unknown");
            
            // Use SimpleDateFormat with UTC timezone for consistency
            rootJson.put("timestamp", ISO8601_FORMAT.format(new Date()));
            
            // 添加会话统计信息
            long currentTime = System.currentTimeMillis();
            rootJson.put("sessionStartTime", sessionStartTime);
            rootJson.put("sessionEndTime", currentTime);
            rootJson.put("sessionDuration", currentTime - sessionStartTime);
            rootJson.put("totalInteractionCount", totalInteractionCount);
            
            // 添加详细统计信息
            JSONObject sessionStats = getSessionStatistics();
            if (sessionStats != null) {
                rootJson.put("statistics", sessionStats);
            }
            
            // 创建最终的交互数据结构
            JSONObject interactionsJson = createInteractionsJson();
            rootJson.put("interactions", interactionsJson);
            
            // 使用FileLogger的logOrUpdateUiInteraction方法将数据追加到单一文件
            fileLogger.logOrUpdateUiInteraction(rootJson);
            
            Log.d(TAG, "UI interactions saved to file for userId: " + 
                  (userId != null ? userId : "unknown") + 
                  ", taskId: " + (taskId != null ? taskId : "unknown"));
            
        } catch (JSONException e) {
            Log.e(TAG, "Error creating JSON for saving interactions: " + e.getMessage(), e);
        }
    }

    /**
     * 创建交互数据的 JSON 结构
     * @return 格式化的交互数据 JSONObject
     */
    private JSONObject createInteractionsJson() throws JSONException {
        JSONObject interactionsJson = new JSONObject();
        
        // 遍历所有窗口交互数据
        for (Map.Entry<String, JSONObject> entry : windowInteractions.entrySet()) {
            String windowId = entry.getKey();
            JSONObject windowData = entry.getValue();
            
            // 获取窗口名称
            String windowName = "unknown";
            if (windowData.has("windowName")) {
                windowName = windowData.getString("windowName");
                // 创建一个新的 JSONObject，不包含 windowName 键
                JSONObject elementInteractions = new JSONObject();
                
                // 复制所有元素交互数据（除了 windowName）
                JSONArray windowDataNames = windowData.names();
                if (windowDataNames != null) {
                    for (int i = 0; i < windowDataNames.length(); i++) {
                        String key = windowDataNames.getString(i);
                        if (!"windowName".equals(key)) {
                            elementInteractions.put(key, windowData.get(key));
                        }
                    }
                }
                
                // 创建窗口对象，包含窗口名称和元素交互
                JSONObject windowObject = new JSONObject();
                windowObject.put("windowName", windowName);
                windowObject.put("elements", elementInteractions);
                
                // 将窗口对象添加到交互 JSON 中
                interactionsJson.put(windowId, windowObject);
            } else {
                // 如果没有窗口名称，直接添加窗口数据
                interactionsJson.put(windowId, windowData);
            }
        }
        
        return interactionsJson;
    }

    /**
     * Generates a more robust window ID based on the node's window properties.
     * For now, it uses a simplified window ID.
     *
     * @param node The AccessibilityNodeInfo from which to derive the window ID.
     * @return A string representing the current window ID.
     */
    private String getCurrentWindowId(AccessibilityNodeInfo node) {
        if (node != null && node.getWindowId() != -1) {
            // A more robust ID could involve window title or other properties if available
            // For now, just using the integer ID as a string.
            return "window_" + node.getWindowId();
        }
        return "default_window"; // Fallback
    }

    /**
     * Safely converts a CharSequence to a String, returning an empty string if the CharSequence is null.
     *
     * @param cs The CharSequence to convert.
     * @return The string representation or an empty string.
     */
    private Object getSafeString(CharSequence cs) {
        return (cs == null) ? JSONObject.NULL : cs.toString();
    }

    /**
     * Generates a unique hash-based identifier for an AccessibilityNodeInfo.
     * The ID is generated using viewIdResourceName, className, and rect coordinates.
     * 
     * 生成过程：
     * 1. 收集组成信息：viewIdResourceName（如果为空则使用"null"）、className（如果为空则使用"null"）、rect（边界矩形的四个坐标值）
     * 2. 拼接原始字符串：viewIdResourceName_className_left_top_right_bottom
     * 3. 生成哈希值：使用字符串的hashCode()方法生成哈希值
     * 4. 转换为无符号整数(toUInt())再转换为16进制字符串
     * 5. 最终键格式：element_abc123def
     * 
     * @param node The AccessibilityNodeInfo to generate hash ID for
     * @return A string hash ID in format "element_hexHashValue"
     */
    private String generateElementHashId(AccessibilityNodeInfo node) {
        if (node == null) {
            return "element_null";
        }
        
        // 收集组成信息
        String viewIdResourceName = node.getViewIdResourceName();
        if (viewIdResourceName == null || viewIdResourceName.isEmpty()) {
            viewIdResourceName = "null";
        }
        
        CharSequence classNameSeq = node.getClassName();
        String className = (classNameSeq != null) ? classNameSeq.toString() : "null";
        if (className.isEmpty()) {
            className = "null";
        }
        
        // 获取边界矩形
        Rect rect = new Rect();
        node.getBoundsInScreen(rect);
        
        // 拼接原始字符串：viewIdResourceName_className_left_top_right_bottom
        String rawString = viewIdResourceName + "_" + className + "_" + 
                          rect.left + "_" + rect.top + "_" + rect.right + "_" + rect.bottom;
        
        // 生成哈希值并转换为无符号整数的16进制字符串
        int hashCode = rawString.hashCode();
        // 转换为无符号整数再转为16进制字符串
        String hexHash = Integer.toHexString(hashCode);
        
        // 最终键格式
        return "element_" + hexHash;
    }
}

