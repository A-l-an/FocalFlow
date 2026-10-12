package com.google.android.accessibility.utils;

/**
 * 会话配置类，用于存储可配置的用户和任务标识符
 * 所有日志记录模块（ui_elements_logs, ui_interaction_logs, virtual_tree_logs, node_mapping_log等）
 */
public class SessionConfig {

    public static String EXTERNAL_USER_ID = "User_Test";
    public static String EXTERNAL_TASK_ID = "Task_3_4";
    
    /**
     * 设置用户ID和任务ID
     * @param userId 用户标识符
     * @param taskId 任务标识符
     */
    public static void setSessionIds(String userId, String taskId) {
        EXTERNAL_USER_ID = userId;
        EXTERNAL_TASK_ID = taskId;
    }
    
    /**
     * 获取当前用户ID
     */
    public static String getUserId() {
        return EXTERNAL_USER_ID;
    }
    
    /**
     * 获取当前任务ID
     */
    public static String getTaskId() {
        return EXTERNAL_TASK_ID;
    }
} 