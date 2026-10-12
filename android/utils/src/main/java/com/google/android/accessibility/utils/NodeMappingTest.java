package com.google.android.accessibility.utils;

import android.content.Context;
import android.util.Log;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat;
import com.google.android.libraries.accessibility.utils.log.LogUtils;

/**
 * 简单的测试类用于验证NodeMappingManager功能
 */
public class NodeMappingTest {

    private static final String TAG = "NodeMappingTest";
    private static final String EXECUTION_TAG = "MY_APP_TEST_DEBUG";

    /**
     * 执行基本的映射测试
     * @param context 应用上下文
     */
    public static void runBasicTest(Context context) {
        Log.e(EXECUTION_TAG, "!!!!!!!!!! NodeMappingTest.runBasicTest ENTERED !!!!!!!!!");
        LogUtils.d(TAG, "=== Starting NodeMappingManager Basic Test ===");
        
        try {
            // 1. 创建NodeMappingManager实例
            LogUtils.d(TAG, "Creating NodeMappingManager instance...");
            NodeMappingManager mappingManager = new NodeMappingManager(context);
            
            // 2. 设置会话信息
            LogUtils.d(TAG, "Setting session info...");
            mappingManager.setSessionInfo(SessionConfig.EXTERNAL_USER_ID, SessionConfig.EXTERNAL_TASK_ID);
            
            // 3. 测试添加映射（使用模拟节点）
            LogUtils.d(TAG, "Testing addMapping with mock data...");
            
            // 创建虚拟节点ID
            String virtualNodeId1 = NodeMappingManager.generateVirtualNodeId();
            String virtualNodeId2 = NodeMappingManager.generateVirtualNodeId();
            
            LogUtils.d(TAG, "Generated virtual node IDs: %s, %s", virtualNodeId1, virtualNodeId2);
            
            // 注意：这里我们不能真正创建AccessibilityNodeInfoCompat实例，因为那需要真实的节点
            // 但我们可以触发保存空映射的操作
            
            // 4. 直接调用saveMappingsToFile来测试文件写入
            LogUtils.d(TAG, "Attempting to save empty mappings to test file creation...");
            mappingManager.clearAllMappings(); // 这会触发saveMappingsToFile()
            
            // 5. 测试虚拟树构建器集成
            LogUtils.d(TAG, "Setting mapping manager in VirtualTreeBuilder...");
            VirtualTreeBuilder.setMappingManager(mappingManager);
            
            LogUtils.d(TAG, "=== NodeMappingManager Basic Test Completed ===");
            
        } catch (Exception e) {
            LogUtils.e(TAG, "Error during basic test: " + e.getMessage(), e);
        }
        Log.e(EXECUTION_TAG, "!!!!!!!!!! NodeMappingTest.runBasicTest EXITED !!!!!!!!!");
    }

    /**
     * 测试文件日志功能
     * @param context 应用上下文
     */
    public static void testFileLogging(Context context) {
        Log.e(EXECUTION_TAG, "!!!!!!!!!! NodeMappingTest.testFileLogging ENTERED !!!!!!!!!");
        LogUtils.d(TAG, "=== Testing FileLogger functionality ===");
        
        try {
            // 直接测试FileLogger
            FileLogger fileLogger = new FileLogger(context);
            
            // 使用 SessionConfig 中定义的统一用户和任务ID
            fileLogger.initializeSessionDirectories(SessionConfig.EXTERNAL_USER_ID, SessionConfig.EXTERNAL_TASK_ID);
            
            // 测试设置基础目录
            LogUtils.d(TAG, "Testing FileLogger base directory setup...");
            String testPath = context.getExternalFilesDir(null) + "/screen_reader_logs/test_mappings";
            fileLogger.setBaseLogDirectory(testPath);
            
            // 启用node_mapping_log类型
            LogUtils.d(TAG, "Enabling node_mapping_log type...");
            fileLogger.enableLogType("node_mapping_log");
            
            // 测试写入JSON
            LogUtils.d(TAG, "Testing JSON writing...");
            org.json.JSONObject testJson = new org.json.JSONObject();
            testJson.put("test", "data");
            testJson.put("timestamp", System.currentTimeMillis());
            
            fileLogger.logJson("node_mappings_log_test_123456", testJson);
            
            LogUtils.d(TAG, "=== FileLogger test completed ===");
            
        } catch (Exception e) {
            LogUtils.e(TAG, "Error during FileLogger test: " + e.getMessage(), e);
        }
        Log.e(EXECUTION_TAG, "!!!!!!!!!! NodeMappingTest.testFileLogging EXITED !!!!!!!!!");
    }
} 