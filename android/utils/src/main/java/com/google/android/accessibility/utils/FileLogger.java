package com.google.android.accessibility.utils;

import android.content.Context;
import android.util.Log;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.FileReader;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;
import org.checkerframework.checker.nullness.qual.Nullable;

/**
 * A utility class for logging text and JSON data to files.
 */
public class FileLogger {

  private static final String TAG = "FileLogger";

  private File baseLogDir;
  private String userId = "default_user";
  private String taskId = "default_task";
  private Context context;
  private TransportArtifactStore transportArtifacts;
  
  // 日志类型启用标志
  private boolean ttsLogEnabled = false;
  private boolean uiElementLogEnabled = false;
  private boolean virtualTreeLogEnabled = false;
  private boolean interactionLogEnabled = false;
  private boolean nodeMappingLogEnabled = false;
  private boolean nodeNamesLogEnabled = false;
  private boolean pcUpdatedVirtualTreeLogEnabled = false; // 新增PC更新虚拟树日志标志

  // TTS日志专用文件，每次编译一个
  private File ttsLogFile;
  private boolean ttsLogFileInitialized = false;

  // UI交互日志专用文件，每次编译一个
  private File uiInteractionLogFile;
  private boolean uiInteractionLogFileInitialized = false;

  // 新增：用于UI_UPDATED信号去抖动的变量

  // 新增：用于ROLE信号去抖动的变量
  private long lastRoleSignalTime = 0;

  /**
   * Constructs a FileLogger instance.
   *
   * @param context The application context.
   */
  public FileLogger(Context context) {
    this.context = context.getApplicationContext();
    // Set up a default baseLogDir
    File externalFilesDir = this.context.getExternalFilesDir(null);
    if (externalFilesDir != null) {
      baseLogDir = new File(externalFilesDir, "screen_reader_logs");
    } else {
      // Fallback to internal storage if external storage is not available
      baseLogDir = new File(this.context.getFilesDir(), "screen_reader_logs");
    }

    if (!baseLogDir.exists()) {
      if (!baseLogDir.mkdirs()) {
        Log.e(TAG, "Failed to create base log directory");
      }
    }
  }

  /**
   * 启用或禁用特定类型的日志记录
   * 
   * @param ttsLog 是否启用TTS语音日志
   * @param uiElementLog 是否启用UI元素日志
   * @param virtualTreeLog 是否启用虚拟树日志
   * @param interactionLog 是否启用交互日志
   */
  public void setLogTypesEnabled(
      boolean ttsLog, 
      boolean uiElementLog, 
      boolean virtualTreeLog, 
      boolean interactionLog) {
    this.ttsLogEnabled = ttsLog;
    this.uiElementLogEnabled = uiElementLog;
    this.virtualTreeLogEnabled = virtualTreeLog;
    this.interactionLogEnabled = interactionLog;
    
    Log.d(TAG, String.format(
        "日志类型设置 - TTS: %b, UI元素: %b, 虚拟树: %b, 交互: %b",
        ttsLog, uiElementLog, virtualTreeLog, interactionLog));
    
  }
  

  
  /**
   * 初始化TTS日志文件（每次编译只创建一个文件）
   */
  private void initializeTtsLogFile() {
    if (ttsLogFileInitialized) {
      return; // 已经初始化过了，不需要重复初始化
    }
    
    File ttsLogDir = new File(baseLogDir, "tts_logs");
    if (!ttsLogDir.exists()) {
      if (!ttsLogDir.mkdirs()) {
        Log.e(TAG, "创建TTS日志目录失败");
        return;
      }
    }
    
    // 创建单一的TTS日志文件，使用会话开始时间戳，并包含用户ID和任务ID
    // 直接在tts_logs目录下创建文件，不在用户ID和任务ID的子目录中
    String sessionTimestamp = new SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(new Date());
    ttsLogFile = new File(ttsLogDir, "tts_log_" + userId + "_" + taskId + "_" + sessionTimestamp + ".txt");
    ttsLogFileInitialized = true;
    
    Log.d(TAG, "TTS日志文件已初始化");
    
    // 写入文件头部信息
    try (FileWriter fw = new FileWriter(ttsLogFile, false); // 创建新文件
         BufferedWriter bw = new BufferedWriter(fw)) {
      bw.write("=== TalkBack TTS 语音记录 ===");
      bw.newLine();
      bw.write("会话开始时间: " + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(new Date()));
      bw.newLine();
      bw.write("用户ID: " + userId);
      bw.newLine();
      bw.write("任务ID: " + taskId);
      bw.newLine();
      bw.write("格式: [时间] 播报内容");
      bw.newLine();
      bw.write("========================");
      bw.newLine();
    } catch (IOException e) {
      Log.e(TAG, "初始化TTS日志文件时出错" + " (" + e.getClass().getSimpleName() + ")");
    }
  }
  
  /**
   * 记录简化的TTS语音播报内容（只记录时间和内容）
   * 
   * @param spokenText 播报的语音内容
   */
  public void logTtsSimple(String spokenText) {
    if (!ttsLogEnabled || spokenText == null || spokenText.trim().isEmpty()) {
      return;
    }
    
    // 确保TTS日志文件已初始化
    if (!ttsLogFileInitialized) {
      initializeTtsLogFile();
    }
    
    if (ttsLogFile == null) {
      Log.e(TAG, "TTS日志文件未初始化，无法记录");
      return;
    }
    
    try (FileWriter fw = new FileWriter(ttsLogFile, true); // 追加模式
         BufferedWriter bw = new BufferedWriter(fw)) {
      String timestamp = new SimpleDateFormat("MM-dd HH:mm:ss", Locale.getDefault()).format(new Date());
      bw.write("[" + timestamp + "] " + spokenText.trim());
      bw.newLine();
    } catch (IOException e) {
      Log.e(TAG, "记录TTS语音内容时出错" + " (" + e.getClass().getSimpleName() + ")");
    }
  }

  /**
   * 初始化UI交互日志文件（每次编译只创建一个文件）
   */
  private void initializeUiInteractionLogFile() {
    if (uiInteractionLogFileInitialized || !interactionLogEnabled) {
      return; // 已经初始化过了，或者交互日志未启用
    }
    
    File interactionLogDir = getLogTypeDir("ui_interaction_logs");
    if (interactionLogDir == null) {
      Log.e(TAG, "UI交互日志目录为null，无法初始化文件");
      return;
    }
    
    // 创建单一的UI交互日志文件，使用会话开始时间戳，并包含用户ID和任务ID
    String sessionTimestamp = new SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(new Date());
    uiInteractionLogFile = new File(interactionLogDir, "ui_interaction_log_" + userId + "_" + taskId + "_" + sessionTimestamp + ".json");
    uiInteractionLogFileInitialized = true;
    
    Log.d(TAG, "UI交互日志文件已初始化");
    
    // 如果文件不存在，写入初始JSON结构
    if (!uiInteractionLogFile.exists()) {
      try (FileWriter fw = new FileWriter(uiInteractionLogFile, false); // 创建新文件
           BufferedWriter bw = new BufferedWriter(fw)) {
        JSONObject initialLog = new JSONObject();
        JSONObject sessionInfo = new JSONObject();
        sessionInfo.put("userId", userId);
        sessionInfo.put("taskId", taskId);
        sessionInfo.put("startTime", new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(new Date()));
        initialLog.put("sessionInfo", sessionInfo);
        initialLog.put("interactions", new JSONObject()); // 改为JSONObject字典格式
        initialLog.put("sessionStartTime", System.currentTimeMillis());
        initialLog.put("totalInteractionCount", 0);
        bw.write(initialLog.toString(2));
        Log.d(TAG, "初始化新的UI交互日志文件");
      } catch (IOException | org.json.JSONException e) {
        Log.e(TAG, "初始化UI交互日志文件时出错" + " (" + e.getClass().getSimpleName() + ")");
      }
    }
  }
  

  /**
   * 启用指定的日志类型
   * @param logType 要启用的日志类型
   */
  public void enableLogType(String logType) {
    switch (logType) {
      case "tts_logs":
        ttsLogEnabled = true;
        break;
      case "ui_elements_logs":
        uiElementLogEnabled = true;
        break;
      case "virtual_tree_logs":
        virtualTreeLogEnabled = true;
        break;
      case "ui_interaction_logs":
        interactionLogEnabled = true;
        break;
      case "node_mapping_log":
        nodeMappingLogEnabled = true;
        break;
      case "node_names_log":
        nodeNamesLogEnabled = true;
        break;
      case "pc_updated_virtual_tree_logs":
        pcUpdatedVirtualTreeLogEnabled = true;
        break;
      default:
        Log.w(TAG, "Unknown log type");
    }
  }

  /**
   * 检查指定的日志类型是否已启用
   */
  public boolean isLogTypeEnabled(String logType) {
    switch (logType) {
      case "tts_logs":
        return ttsLogEnabled;
      case "ui_elements_logs":
        return uiElementLogEnabled;
      case "virtual_tree_logs":
        return virtualTreeLogEnabled;
      case "ui_interaction_logs":
        return interactionLogEnabled;
      case "node_mapping_log":
        return nodeMappingLogEnabled;
      case "node_names_log":
        return nodeNamesLogEnabled;
      case "pc_updated_virtual_tree_logs":
        return pcUpdatedVirtualTreeLogEnabled;
      default:
        return false;
    }
  }

  /**
   * Initializes session-specific directories for logging.
   *
   * @param userId The user ID for the current session.
   * @param taskId The task ID for the current session.
   */
  public void initializeSessionDirectories(String userId, String taskId) {
    this.userId = userId;
    this.taskId = taskId;
    
    // 发送ROLE信号到PC（带去抖动机制）
    long currentTime = System.currentTimeMillis();
    // 2秒内不重复发送，实现去抖动
    if (currentTime - lastRoleSignalTime > 2000) {
      PcConnectionManager.getInstance().sendRoleSignal(userId, taskId);
      lastRoleSignalTime = currentTime;
      Log.d(TAG, "ROLE signal sent");
    } else {
      Log.d(TAG, "ROLE signal debounced, skipping.");
    }
    
    // 如果交互日志已启用但还未初始化，则初始化
    if (interactionLogEnabled && !uiInteractionLogFileInitialized) {
      initializeUiInteractionLogFile();
    }
  }

  /**
   * 获取特定类型日志的目录
   * 对于tts_logs，返回类型目录
   * 对于其他类型，返回完整的目录结构: screen_reader_logs/[type]/[userId]/[taskId]/
   */
  private File getLogTypeDir(String logType) {
    if (baseLogDir == null) {
      Log.e(TAG, "Base log directory is not initialized.");
      return null;
    }
    
    File typeDir = new File(baseLogDir, logType);
    
    // 对于tts_logs，只返回类型目录，不包含用户ID和任务ID的子目录
    if (logType.equals("tts_logs")) {
      if (!typeDir.exists()) {
        if (!typeDir.mkdirs()) {
          Log.e(TAG, "Failed to create log type directory");
          return null;
        }
      }
      return typeDir;
    }
    
    // 对于其他类型，返回完整的目录结构
    File userDir = new File(typeDir, userId);
    File taskDir = new File(userDir, taskId);
    
    if (!taskDir.exists()) {
      if (!taskDir.mkdirs()) {
        Log.e(TAG, "Failed to create log type directory");
        return null;
      }
    }
    return taskDir;
  }

  /**
   * Helper method to construct a log file within a specific log type directory.
   * 对于tts_logs，直接在类型目录下创建文件
   * 对于其他类型，在用户ID和任务ID的子目录中创建文件
   *
   * @param logType The log type directory name (e.g., "tts_logs", "ui_elements_logs").
   * @param fileNamePrefix The prefix for the log file name.
   * @param extension The file extension (e.g., "txt", "json").
   * @return The File object for the log file, or null if directory creation fails.
   */
  private File getLogFile(String logType, String fileNamePrefix, String extension) {
    File typeDir = getLogTypeDir(logType);
    if (typeDir == null) {
      return null;
    }

    String timestamp = new SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(new Date());
    String fileName = fileNamePrefix + "_" + userId + "_" + taskId + "_" + timestamp + "." + extension;

    return new File(typeDir, fileName);
  }

  /**
   * Logs text data to a file.
   *
   * @param fileNamePrefix The prefix for the log file name.
   * @param text The text content to log.
   */
  public void logText(String fileNamePrefix, String text) {
    String logType = determineLogType(fileNamePrefix);
    if (!isLogTypeEnabled(logType)) {
      return; // 如果该类型的日志未启用，则不记录
    }
    
    File logFile = getLogFile(logType, fileNamePrefix, "txt");
    if (logFile == null) {
      Log.e(TAG, "Cannot log text, failed to obtain log file reference.");
      return;
    }

    try (FileWriter fw = new FileWriter(logFile, true); // true for append mode
        BufferedWriter bw = new BufferedWriter(fw)) {
      String timestamp = new SimpleDateFormat("MM-dd HH:mm:ss", Locale.getDefault()).format(new Date());
      bw.write(timestamp + ": " + text);
      bw.newLine();
    } catch (IOException e) {
      Log.e(TAG, "Error writing text to log file" + " (" + e.getClass().getSimpleName() + ")");
    }
  }

  /**
   * Logs JSON object data to a file.
   *
   * @param fileNamePrefix The prefix for the log file name.
   * @param jsonData The JSONObject to log.
   */
  public void logJson(String fileNamePrefix, JSONObject jsonData) {
    logJson(fileNamePrefix, jsonData, null);
  }

  /** Optional UI history must commit under the same ownership lock as pause/invalidation. */
  public void logCapturedUiElements(SnapshotContext capture, JSONObject hierarchyJson) {
    VirtualTreeManager trees = VirtualTreeManager.getInstance();
    synchronized (trees) {
      if (trees.isPaused() || !trees.isCurrent(capture)) return;
      logJson("ui_elements_log", hierarchyJson);
    }
  }

  /**
   * Logs JSON object data to an explicitly enabled debug file.
   *
   * @param fileNamePrefix The prefix for the log file name.
   * @param jsonData The JSONObject to log.
   * @param interaction Retained for source compatibility; debug logging never sends a request.
   */
  public void logJson(String fileNamePrefix, JSONObject jsonData, @Nullable JSONObject interaction) {
    String logType = determineLogType(fileNamePrefix);
    if (!isLogTypeEnabled(logType)) {
      return;
    }

    File logFile = getLogFile(logType, fileNamePrefix, "json");
    if (logFile == null) {
      Log.e(TAG, "Failed to get log file for");
      return;
    }
    
    Log.d(TAG, "Attempting to write JSON to file");

    try {
      // 为UI元素和虚拟树日志添加时间戳信息
      if (fileNamePrefix.startsWith("ui_elements_log") || fileNamePrefix.startsWith("virtual_tree_log")) {
        // 创建包装对象以符合参考代码格式
        JSONObject wrappedData = new JSONObject();
        String timestamp = new SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(new Date());
        wrappedData.put("captureTimestamp", timestamp);
        
        if (fileNamePrefix.startsWith("ui_elements_log")) {
          wrappedData.put("elements", jsonData);
        } else {
          // 对于虚拟树，jsonData已经包含了必要的结构
          wrappedData = jsonData;
        }
        
        try (FileWriter fw = new FileWriter(logFile); // Overwrite mode for JSON objects
            BufferedWriter bw = new BufferedWriter(fw)) {
          bw.write(wrappedData.toString(4)); // Pretty print with an indent factor of 4
        }

      } else {
        try (FileWriter fw = new FileWriter(logFile); // Overwrite mode for JSON objects
            BufferedWriter bw = new BufferedWriter(fw)) {
          bw.write(jsonData.toString(4)); // Pretty print with an indent factor of 4
        }
      }
    } catch (IOException e) {
      Log.e(TAG, "Error writing JSON object to log file" + " (" + e.getClass().getSimpleName() + ")");
    } catch (org.json.JSONException e) {
      Log.e(TAG, "Error converting JSON object to string" + " (" + e.getClass().getSimpleName() + ")");
    }
  }

  /** Initializes the one operational VAT slot. Called only by the service that owns transport. */
  public synchronized void initializeTransport() {
    if (transportArtifacts != null) {
      return;
    }
    try {
      transportArtifacts = new TransportArtifactStore(baseLogDir);
    } catch (IOException e) {
      Log.e(TAG, "Cannot initialize VAT transport storage (" + e.getClass().getSimpleName() + ")");
    }
  }

  /**
   * Publishes a completed current capture envelope, even with debug logs disabled.
   * The shared transport scheduler retains the latest trailing request within its two-second limit.
   */
  public synchronized java.util.concurrent.CompletableFuture<JSONObject> publishVirtualTree(SnapshotContext capture, JSONObject virtualTree, @Nullable JSONObject interaction) {
    if (transportArtifacts == null) {
      Log.e(TAG, "VAT transport storage is unavailable");
      return java.util.concurrent.CompletableFuture.completedFuture(null);
    }
    try {
      synchronized (VirtualTreeManager.getInstance()) {
        if (VirtualTreeManager.getInstance().isPaused() || !VirtualTreeManager.getInstance().isCurrent(capture)) return java.util.concurrent.CompletableFuture.completedFuture(null);
        // Pause and ownership are checked before optional history as well as transport.
        logJson("virtual_tree_log", virtualTree);
        transportArtifacts.write(capture.envelope(virtualTree).toString(4));
        return PcConnectionManager.getInstance().requestCapturedUpdate(capture, interaction);
      }
    } catch (IOException | org.json.JSONException e) {
      Log.e(TAG, "Cannot publish VAT transport snapshot (" + e.getClass().getSimpleName() + ")");
    }
    return java.util.concurrent.CompletableFuture.completedFuture(null);
  }

  /** Removes the owned transport slot and prevents queued writes after service shutdown. */
  public synchronized void closeTransport() {
    if (transportArtifacts != null) {
      try {
        transportArtifacts.close();
      } catch (IOException e) {
        Log.e(TAG, "Cannot clear VAT transport storage (" + e.getClass().getSimpleName() + ")");
      }
    }
  }

  /**
   * Logs JSON array data to a file.
   *
   * @param fileNamePrefix The prefix for the log file name.
   * @param jsonArrayData The JSONArray to log.
   */
  public void logJson(String fileNamePrefix, JSONArray jsonArrayData) {
    String logType = determineLogType(fileNamePrefix);
    if (!isLogTypeEnabled(logType)) {
      return; // 如果该类型的日志未启用，则不记录
    }
    
    File logFile = getLogFile(logType, fileNamePrefix, "json");
    if (logFile == null) {
      Log.e(TAG, "Cannot log JSON array, failed to obtain log file reference.");
      return;
    }

    try (FileWriter fw = new FileWriter(logFile); // Overwrite mode for JSON arrays
        BufferedWriter bw = new BufferedWriter(fw)) {
      bw.write(jsonArrayData.toString(4)); // Pretty print with an indent factor of 4
    } catch (IOException e) {
      Log.e(TAG, "Error writing JSON array to log file" + " (" + e.getClass().getSimpleName() + ")");
    } catch (org.json.JSONException e) {
      Log.e(TAG, "Error converting JSON array to string" + " (" + e.getClass().getSimpleName() + ")");
    }
  }
  
  /**
   * 根据文件名前缀确定日志类型
   */
  private String determineLogType(String fileNamePrefix) {
    if (fileNamePrefix.startsWith("tts_log")) {
      return "tts_logs";
    } else if (fileNamePrefix.startsWith("ui_elements_log")) {
      return "ui_elements_logs";
    } else if (fileNamePrefix.startsWith("virtual_tree_log")) {
      return "virtual_tree_logs";
    } else if (fileNamePrefix.startsWith("ui_interaction_log")) {
      return "ui_interaction_logs";
    } else if (fileNamePrefix.startsWith("node_mappings_log")) {
      return "node_mapping_log";
    } else if (fileNamePrefix.startsWith("node_names_log")) {
      return "node_names_log";
    } else if (fileNamePrefix.startsWith("pc_updated_virtual_tree_log")) {
      return "pc_updated_virtual_tree_logs";
    } else {
      return "unknown";
    }
  }

  /**
   * Sets a custom base directory for logs.
   *
   * @param path The absolute path to the new base log directory.
   */
  public void setBaseLogDirectory(String path) {
    Log.d(TAG, "Attempting to set base log directory to");
    if (path == null || path.isEmpty()) {
      Log.e(TAG, "setBaseLogDirectory: Provided path is null or empty.");
      return;
    }
    File newBaseDir = new File(path);
    if (!newBaseDir.exists()) {
      Log.d(TAG, "Base log directory does not exist, attempting to create");
      if (!newBaseDir.mkdirs()) {
        Log.e(TAG, "Failed to create base log directory");
        return;
      }
      Log.d(TAG, "Successfully created base log directory");
    }
    this.baseLogDir = newBaseDir;
    Log.d(TAG, "Successfully set base log directory to");

    // 清除已初始化的特定日志文件，以便它们可以使用新的baseLogDir重新初始化
    ttsLogFileInitialized = false;
    uiInteractionLogFileInitialized = false;

    // Re-initialize session directories if userId and taskId are already set
    if (!"default_user".equals(userId) || !"default_task".equals(taskId)) {
        initializeSessionDirectories(this.userId, this.taskId);
    }
  }

  /**
   * 记录或更新UI交互到单一的JSON文件中
   * 
   * @param singleInteractionEvent 单次交互事件的JSONObject
   */
  public synchronized void logOrUpdateUiInteraction(JSONObject singleInteractionEvent) {
    if (!interactionLogEnabled || !uiInteractionLogFileInitialized || uiInteractionLogFile == null) {
      Log.w(TAG, "UI交互日志未启用或文件未初始化，跳过记录");
      return;
    }

    try {
      JSONObject rootObject;
      // 文件必须存在，因为它在initializeUiInteractionLogFile中创建
      if (uiInteractionLogFile.exists() && uiInteractionLogFile.length() > 0) {
        // 读取现有内容
        StringBuilder contentBuilder = new StringBuilder();
        try (java.io.BufferedReader reader = new java.io.BufferedReader(new FileReader(uiInteractionLogFile))) {
          String line;
          while ((line = reader.readLine()) != null) {
            contentBuilder.append(line);
          }
        }
        if (contentBuilder.length() == 0) {
          // 文件存在但为空，创建新的 rootObject
          rootObject = new JSONObject();
          JSONObject sessionInfo = new JSONObject();
          sessionInfo.put("userId", userId);
          sessionInfo.put("taskId", taskId);
          sessionInfo.put("startTime", new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(new Date()));
          rootObject.put("sessionInfo", sessionInfo);
          rootObject.put("interactions", new JSONObject()); // 使用JSONObject字典格式
          rootObject.put("sessionStartTime", System.currentTimeMillis());
        } else {
          rootObject = new JSONObject(contentBuilder.toString());
        }
      } else {
        // 如果文件不存在或为空（虽然理论上应该在initialize时创建好）
        rootObject = new JSONObject();
        JSONObject sessionInfo = new JSONObject();
        sessionInfo.put("userId", userId);
        sessionInfo.put("taskId", taskId);
        sessionInfo.put("startTime", new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(new Date()));
        rootObject.put("sessionInfo", sessionInfo);
        rootObject.put("interactions", new JSONObject()); // 使用JSONObject字典格式
        rootObject.put("sessionStartTime", System.currentTimeMillis());
      }

      // 获取现有的interactions字典，如果不存在或者是旧的数组格式，则创建新的
      JSONObject interactionsDict = rootObject.optJSONObject("interactions");
      if (interactionsDict == null) {
        // 检查是否存在旧的数组格式
        if (rootObject.has("interactions")) {
          Log.w(TAG, "检测到旧的数组格式交互数据，正在转换为字典格式");
        }
        interactionsDict = new JSONObject();
      }
      
      // 合并新的交互数据到现有的interactions字典中
      JSONObject newInteractions = singleInteractionEvent.optJSONObject("interactions");
      if (newInteractions != null) {
        // 遍历新交互数据中的每个窗口
        JSONArray windowIds = newInteractions.names();
        if (windowIds != null) {
          for (int i = 0; i < windowIds.length(); i++) {
            String windowId = windowIds.getString(i);
            JSONObject newWindowData = newInteractions.getJSONObject(windowId);
            
            // 获取现有的窗口数据或创建新的
            JSONObject existingWindowData = interactionsDict.optJSONObject(windowId);
            if (existingWindowData == null) {
              // 窗口不存在，直接添加
              interactionsDict.put(windowId, newWindowData);
            } else {
              // 窗口已存在，需要合并elements
              String windowName = newWindowData.optString("windowName", "unknown");
              existingWindowData.put("windowName", windowName); // 更新窗口名称
              
              JSONObject existingElements = existingWindowData.optJSONObject("elements");
              if (existingElements == null) {
                existingElements = new JSONObject();
                existingWindowData.put("elements", existingElements);
              }
              
              JSONObject newElements = newWindowData.optJSONObject("elements");
              if (newElements != null) {
                // 合并新的元素数据
                JSONArray elementIds = newElements.names();
                if (elementIds != null) {
                  for (int j = 0; j < elementIds.length(); j++) {
                    String elementId = elementIds.getString(j);
                    JSONObject newElementData = newElements.getJSONObject(elementId);
                    existingElements.put(elementId, newElementData); // 覆盖或添加元素数据
                  }
                }
              }
            }
          }
        }
      }
      
      rootObject.put("interactions", interactionsDict);
      
      // 计算总交互数量（基于所有窗口中的元素总数）
      int totalInteractionCount = 0;
      JSONArray windowIds = interactionsDict.names();
      if (windowIds != null) {
        for (int i = 0; i < windowIds.length(); i++) {
          String windowId = windowIds.getString(i);
          JSONObject windowData = interactionsDict.getJSONObject(windowId);
          JSONObject elements = windowData.optJSONObject("elements");
          if (elements != null) {
            JSONArray elementIds = elements.names();
            if (elementIds != null) {
              totalInteractionCount += elementIds.length();
            }
          }
        }
      }
      
      // 更新其他根级别元数据
      rootObject.put("lastUpdateTime", System.currentTimeMillis());
      rootObject.put("totalInteractionCount", totalInteractionCount);
      
      // 从singleInteractionEvent复制其他根级别数据
      if (singleInteractionEvent.has("userId")) {
        rootObject.put("userId", singleInteractionEvent.getString("userId"));
      }
      if (singleInteractionEvent.has("taskId")) {
        rootObject.put("taskId", singleInteractionEvent.getString("taskId"));
      }
      if (singleInteractionEvent.has("timestamp")) {
        rootObject.put("timestamp", singleInteractionEvent.getString("timestamp"));
      }
      if (singleInteractionEvent.has("sessionStartTime")) {
        rootObject.put("sessionStartTime", singleInteractionEvent.getLong("sessionStartTime"));
      }
      if (singleInteractionEvent.has("sessionEndTime")) {
        rootObject.put("sessionEndTime", singleInteractionEvent.getLong("sessionEndTime"));
      }
      if (singleInteractionEvent.has("sessionDuration")) {
        rootObject.put("sessionDuration", singleInteractionEvent.getLong("sessionDuration"));
      }
      if (singleInteractionEvent.has("statistics")) {
        rootObject.put("statistics", singleInteractionEvent.getJSONObject("statistics"));
      }

      // 写回文件 (覆盖)
      try (FileWriter fw = new FileWriter(uiInteractionLogFile, false);
           BufferedWriter bw = new BufferedWriter(fw)) {
        bw.write(rootObject.toString(2));
      }

    } catch (IOException | org.json.JSONException e) {
      Log.e(TAG, "记录或更新UI交互时出错" + " (" + e.getClass().getSimpleName() + ")");
    }
  }

  /**
   * 获取基础日志目录路径
   * @return 基础日志目录的绝对路径
   */
  public String getBaseLogDirectory() {
    return baseLogDir.getAbsolutePath();
  }
}
