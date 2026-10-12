package com.example.blv_mobile_app

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.view.accessibility.AccessibilityEvent
// import android.speech.tts.TextToSpeech // Already handled by TtsManager integration
import android.util.Log
import java.util.Locale
import android.os.Handler
import android.os.Looper
import android.content.Intent
import android.graphics.PixelFormat
import android.graphics.Rect
import android.content.Context
import java.io.File
import java.io.FileWriter
import java.text.SimpleDateFormat
import java.util.Date
import android.view.MotionEvent
import android.graphics.Path
import android.view.GestureDetector
import android.accessibilityservice.AccessibilityServiceInfo
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import org.json.JSONArray
import java.io.FileOutputStream
import java.util.TimeZone
import android.os.Vibrator
import android.os.VibrationEffect
import android.speech.tts.TextToSpeech // Keep for TtsManager initialization if not already there

// Implement GestureListener
class ScreenReaderService : AccessibilityService(), GestureListener {

    // TTS Manager related (should be from previous subtask, ensure it's here)
    private var tts: TextToSpeech? = null // This should be removed if TtsManager is fully integrated
    private lateinit var ttsManager: TtsManager // Assuming this is correctly initialized from previous task
    private lateinit var logFile: File // This should be removed if TtsManager is fully integrated

    private lateinit var windowManager: WindowManager
    private lateinit var focusOverlayView: FocusOverlayView
    // private lateinit var logFile: File // Managed by TtsManager or specific log managers
    private lateinit var overlayView: View
    private lateinit var uiElementsLogDir: File
    private lateinit var ttsLogDir: File // Used by TtsManager's logFileProvider
    private lateinit var gestureManager: GestureManager // Added GestureManager instance
    private lateinit var uiInteractionLogFile: File
    private val uiInteractions = mutableMapOf<String, JSONObject>()

    // 添加用户ID和任务ID属性
    private var userId: String = "P1"  // 默认用户ID
    private var taskId: String = "Task1"  // 默认任务ID

    // --- Properties moved to GestureManager ---
    // private var lastTapTime: Long = 0
    // private var lastTapX: Float = 0f
    // private var lastTapY: Float = 0f
    // private val doubleTapTimeout = 300

    private var currentFocusedNode: AccessibilityNodeInfo? = null // Kept in Service, passed to GestureManager as needed

    // service-specific scroll cooldown, GestureManager uses its own constants for thresholds
    private var lastScrollTime: Long = 0 
    // private val scrollCooldown = 500 // Moved to GestureManager.SCROLL_COOLDOWN
    // private val SCROLL_THRESHOLD = 15 // Moved to GestureManager.SCROLL_THRESHOLD
    // private var scrollPath = arrayListOf<ScrollDirection>() // Moved to GestureManager
    // private var isScrolling = false // Moved to GestureManager

    // Keep local enum for performFinalScroll signature for now, map from GestureManager.ScrollDirection in listener
     private enum class ScrollDirection(var fingers: Int = 1) {
         UP, DOWN, LEFT, RIGHT, UNKNOWN
     }

    private var isServiceActive = false

    private var lastVisitedElement: String? = null
    private var visitStartTime: Long = 0

    // 在类的顶部添加一个新的Handler
    private val handler = Handler(Looper.getMainLooper())

    // This state is now primarily managed by GestureManager and updated via listener
    private var isLongPressing = false 
    // private var longPressStartTime = 0L // Moved to GestureManager
    // private val LONG_PRESS_THRESHOLD = 500L // Moved to GestureManager.LONG_PRESS_THRESHOLD

    // 在类的顶部添加屏幕尺寸相关属性
    private var screenWidth: Int = 0
    private var screenHeight: Int = 0

    // 在类的顶部添加一个新的属性
    private var isDoubleClickAction = false

    // 在类成员变量区添加一个新的辅助方法，用于检查节点是否是ViewGroup
    private var cachedActiveViewHierarchy: AccessibilityNodeInfo? = null

    // 在ScreenReaderService类中添加
    private var cachedFocusableNodes: List<AccessibilityNodeInfo> = emptyList()
    private var cachedRootHash: Int = 0

    // 在类的成员变量区域添加以下变量
    private var needUpdateCache = true
    private var nodePositionMap = mutableMapOf<Pair<Int, Int>, MutableList<AccessibilityNodeInfo>>()
    private val GRID_CELL_SIZE = 100 // 网格单元大小，单位为像素

    // 添加调试相关变量和方法
    private val DEBUG = false // 设置为true启用详细日志

    private lateinit var screenshotsLogDir: File // 新增：截图目录

    // 新增：最近一次UI更新信号的时间戳
    private var lastUiUpdateTime: Long = 0L

    // 1. 在成员变量区添加Vibrator变量
    private lateinit var vibrator: Vibrator

    // 1. 定义 VirtualNode 数据结构
    private data class VirtualNode(
        val id: String,
        val type: NodeType,
        var canFocus: Boolean,
        val text: CharSequence?,
        val contentDescription: CharSequence?,
        val viewIdResourceName: String?,
        val className: CharSequence?,
        val isClickable: Boolean,
        val isCheckable: Boolean,
        val isChecked: Boolean,
        val isFocusable: Boolean,
        val isEnabled: Boolean,
        val isPassword: Boolean,
        val isSelected: Boolean,
        val bounds: Rect,
        val center: Pair<Int, Int>,
        val realNode: AccessibilityNodeInfo?,
        val children: MutableList<VirtualNode> = mutableListOf(),
        var parent: VirtualNode? = null
    ) {
        enum class NodeType { REAL, STATIC_TEXT }
    }

    // 2. 在ScreenReaderService类中添加虚拟树根节点和可聚焦节点列表
    private var virtualRoot: VirtualNode? = null
    private var focusableVirtualNodes: List<VirtualNode> = emptyList()

    // ========== 虚拟树聚焦索引与状态管理 ========== 
    private var currentVirtualFocusIndex: Int = -1 // 当前聚焦虚拟节点索引
    private var currentFocusedVirtualNode: VirtualNode? = null // 当前聚焦虚拟节点

    // 3. 构建虚拟树方法
    private fun buildVirtualTree() {
        val root = rootInActiveWindow ?: run {
            virtualRoot = null
            focusableVirtualNodes = emptyList()
            currentVirtualFocusIndex = -1
            currentFocusedVirtualNode = null
            focusOverlayView.updateFocusRect(null)
            return
        }
        virtualRoot = buildVirtualNodeRecursive(root, null)
        val focusList = mutableListOf<VirtualNode>()
        collectFocusableVirtualNodes(virtualRoot, focusList)
        focusableVirtualNodes = focusList
        // 默认聚焦第一个
        if (focusableVirtualNodes.isNotEmpty()) {
            setVirtualFocus(0)
        } else {
            currentVirtualFocusIndex = -1
            currentFocusedVirtualNode = null
            focusOverlayView.updateFocusRect(null)
        }
    }

    private fun buildVirtualNodeRecursive(node: AccessibilityNodeInfo, parent: VirtualNode?): VirtualNode {
        val rect = Rect()
        node.getBoundsInScreen(rect)
        val centerX = (rect.left + rect.right) / 2
        val centerY = (rect.top + rect.bottom) / 2
        val text = node.text
        // 只允许text为"Back to Home"的节点可聚焦
        val canFocus = (text?.toString() == "Back to Home" || text?.toString() == "美团外卖" || text?.toString() == "滴滴出行"
            || node.contentDescription?.toString() == "Back to Home" || node.contentDescription?.toString() == "美团外卖" || node.contentDescription?.toString() == "滴滴出行")
        val vNode = VirtualNode(
            id = node.viewIdResourceName ?: "${node.className}_${centerX}_${centerY}",
            type = VirtualNode.NodeType.REAL,
            canFocus = canFocus,
            text = text,
            contentDescription = node.contentDescription,
            viewIdResourceName = node.viewIdResourceName,
            className = node.className,
            isClickable = node.isClickable,
            isCheckable = node.isCheckable,
            isChecked = node.isChecked,
            isFocusable = node.isFocusable,
            isEnabled = node.isEnabled,
            isPassword = node.isPassword,
            isSelected = node.isSelected,
            bounds = Rect(rect),
            center = Pair(centerX, centerY),
            realNode = node,
            children = mutableListOf(),
            parent = parent
        )
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val childVNode = buildVirtualNodeRecursive(child, vNode)
            vNode.children.add(childVNode)
            child.recycle()
        }
        return vNode
    }

    private fun collectFocusableVirtualNodes(node: VirtualNode?, list: MutableList<VirtualNode>) {
        if (node == null) return
        if (node.canFocus) list.add(node)
        for (child in node.children) {
            collectFocusableVirtualNodes(child, list)
        }
    }

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "ScreenReaderService onCreate")
        // Initialize TtsManager (assuming this was done in the previous subtask)
        // If tts and logFile are still here, TtsManager might not be fully integrated yet.
        // For this diff, I'll assume tts related lines are handled by TtsManager setup.
        // If initializeTTS() still exists, it means TtsManager setup is incomplete.
        // Let's assume initializeTTS() and related TextToSpeech properties are removed if TtsManager is used.
        if (!::ttsManager.isInitialized) { // Defensive init for TtsManager
            ttsManager = TtsManager(this) {
                 // Ensure ttsLogDir is initialized before this lambda is called.
                 // initializeLogDirectories() should ideally be called before this.
                if (!::ttsLogDir.isInitialized) {
                    // Temporary minimal log dir init for safety, should be handled by initializeLogDirectories
                    val baseLogDir = File(getExternalFilesDir(null), "screen_reader_logs")
                    ttsLogDir = File(baseLogDir, "tts_logs")
                    if(!ttsLogDir.exists()) ttsLogDir.mkdirs()
                }
                File(ttsLogDir, "tts_log_${SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(Date())}.txt")
            }
        }
        
        gestureManager = GestureManager(this, this) // Initialize GestureManager

        initializeLogDirectories() // Ensure this is called to set up ttsLogDir etc.
        // initializeTTS() // This should be removed if TtsManager handles TTS init.
        
        // 2. 初始化Vibrator
        vibrator = getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        Log.d(TAG, "ScreenReaderService connected")
        // 不要在这里初始化任何功能，只设置基本的服务配置
        setupServiceConfig()
    }

    private fun setupServiceConfig() {
        // 设置服务
        serviceInfo.flags = serviceInfo.flags or AccessibilityServiceInfo.FLAG_REQUEST_TOUCH_EXPLORATION_MODE
        serviceInfo.flags = serviceInfo.flags or AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
        serviceInfo.flags = serviceInfo.flags or AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
        serviceInfo.eventTypes = AccessibilityEvent.TYPES_ALL_MASK
        serviceInfo.feedbackType = AccessibilityServiceInfo.FEEDBACK_SPOKEN
        setServiceInfo(serviceInfo)
        
        Log.d(TAG, "ScreenReaderService basic setup completed")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.d(TAG, "ScreenReaderService onStartCommand")
        if (intent?.action == "START_SCREEN_READER" && !isServiceActive) {
            isServiceActive = true
            
            // 从Intent中获取用户ID和任务ID
            intent.getStringExtra("USER_ID")?.let { newUserId ->
                intent.getStringExtra("TASK_ID")?.let { newTaskId ->
                    setUserAndTask(newUserId, newTaskId)
                    Log.d(TAG, "从Intent中获取用户ID和任务ID: 用户=$newUserId, 任务=$newTaskId")
                }
            }
            
            initializeService()
            Log.d(TAG, "Screen Reader Service activated")
        }
        return START_STICKY
    }

    private fun initializeService() {
        initializeTTS()
        initializeLogDirectories()
        initializeFocusOverlay()
        setupGestureDetection()
        
        // 初始化屏幕尺寸
        val displayMetrics = resources.displayMetrics
        screenWidth = displayMetrics.widthPixels
        screenHeight = displayMetrics.heightPixels
        Log.d(TAG, "Screen dimensions: ${screenWidth}x${screenHeight}")
    }

    private fun setupGestureDetection() {
        // 创建一个透明的覆盖视图来捕获触摸事件
        val wm = getSystemService(WINDOW_SERVICE) as WindowManager
        overlayView = View(this)
        val params = WindowManager.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            android.graphics.PixelFormat.TRANSLUCENT
        )
        wm.addView(overlayView, params)

        // Remove old GestureDetector, delegate to GestureManager
        overlayView.setOnTouchListener { _, event ->
            if (isServiceActive) {
                // Pass necessary state to GestureManager before it handles the event
                gestureManager.currentFocusedNode = this.currentFocusedNode
                gestureManager.isDoubleClickAction = this.isDoubleClickAction

                val handledByManager = gestureManager.onTouchEvent(event)
                
                // Update service state based on changes made by GestureManager (if any)
                this.isDoubleClickAction = gestureManager.isDoubleClickAction
                // isLongPressing is updated via onLongPressStateChanged callback

                return@setOnTouchListener handledByManager
            }
            true // Consume event if service is not active
        }
    }

    // This method should be removed if TtsManager handles all TTS initialization
    private fun initializeTTS() {
        Log.d(TAG, "Initializing TTS")
        tts = TextToSpeech(this) { status ->
            when (status) {
                TextToSpeech.SUCCESS -> {
                    Log.d(TAG, "TTS initialization succeeded")
                    val result = tts?.setLanguage(Locale.getDefault())
                    when (result) {
                        TextToSpeech.LANG_MISSING_DATA -> {
                            Log.e(TAG, "Language data is missing")
                            installLanguageData()
                        }
                        TextToSpeech.LANG_NOT_SUPPORTED -> {
                            Log.e(TAG, "Language is not supported")
                            tts?.setLanguage(Locale.US)
                        }
                        else -> {
                            Log.d(TAG, "Language set successfully")
                            speakOut("TTS is ready")
                        }
                    }
                }
                TextToSpeech.ERROR -> {
                    Log.e(TAG, "TTS initialization failed with ERROR status")
                    retryInitialization()
                }
                else -> {
                    Log.e(TAG, "TTS initialization failed with unknown status: $status")
                    retryInitialization()
                }
            }
        }
    }

    private fun initializeFocusOverlay() {
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        focusOverlayView = FocusOverlayView(this)

        // 获取屏幕实际大小
        val displayMetrics = resources.displayMetrics
        val screenWidth = displayMetrics.widthPixels
        val screenHeight = displayMetrics.heightPixels

        Log.d(TAG, "Screen size: ${screenWidth}x${screenHeight}")

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                    WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS,
            PixelFormat.TRANSLUCENT
        )

        // 明确设置宽度和高度
        params.width = screenWidth
        params.height = screenHeight

        Log.d(TAG, "FocusOverlay params: width=${params.width}, height=${params.height}")

        try {
            windowManager.addView(focusOverlayView, params)
            Log.d(TAG, "FocusOverlay added successfully with params: $params")
            
            // 添加一个延迟的检查，以确保视图大小正确
            focusOverlayView.post {
                val actualWidth = focusOverlayView.width
                val actualHeight = focusOverlayView.height
                Log.d(TAG, "Actual FocusOverlay size: ${actualWidth}x${actualHeight}")
                if (actualWidth != screenWidth || actualHeight != screenHeight) {
                    Log.w(TAG, "FocusOverlay size mismatch! Expected: ${screenWidth}x${screenHeight}, Actual: ${actualWidth}x${actualHeight}")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to add FocusOverlay: ${e.message}")
        }
    }

    private fun initializeLogDirectories() {
        val baseLogDir = File(getExternalFilesDir(null), "screen_reader_logs")
        if (!baseLogDir.exists()) {
            baseLogDir.mkdirs()
        }

        val timestamp = SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(Date())

        // 创建 UI 元素日志目录
        uiElementsLogDir = File(baseLogDir, "ui_elements_logs")
        if (!uiElementsLogDir.exists()) {
            uiElementsLogDir.mkdirs()
        }

        // 使用用户ID和任务ID创建子目录
        val userTaskDir = File(uiElementsLogDir, "$userId/$taskId")
        if (!userTaskDir.exists()) {
            userTaskDir.mkdirs()
        }

        // 更新 uiElementsLogDir 为用户任务目录
        uiElementsLogDir = userTaskDir

        // 新增：创建 screenshots 目录及其用户/任务子目录
        val screenshotsBaseDir = File(baseLogDir, "screenshots")
        if (!screenshotsBaseDir.exists()) {
            screenshotsBaseDir.mkdirs()
        }
        val screenshotsUserTaskDir = File(screenshotsBaseDir, "$userId/$taskId")
        if (!screenshotsUserTaskDir.exists()) {
            screenshotsUserTaskDir.mkdirs()
        }
        screenshotsLogDir = screenshotsUserTaskDir // 可能只需要传递用户名/截图路径

        // 初始化 TTS 日志文件
        ttsLogDir = File(baseLogDir, "tts_logs")
        if (!ttsLogDir.exists()) {
            ttsLogDir.mkdirs()
        }
        logFile = File(ttsLogDir, "tts_log_$timestamp.txt")

        Log.d(TAG, "Log directories initialized: "+ttsLogDir.absolutePath)
        Log.d(TAG, "Screenshots directory initialized: "+screenshotsLogDir.absolutePath) // 新增日志

        // 初始化 UI 交互日志文件
        val uiLogDir = File(baseLogDir, "ui_interaction_logs")
        if (!uiLogDir.exists()) {
            uiLogDir.mkdirs()
        }
        
        // 使用用户ID和任务ID创建UI交互日志的子目录
        val uiUserTaskDir = File(uiLogDir, "$userId/$taskId")
        if (!uiUserTaskDir.exists()) {
            uiUserTaskDir.mkdirs()
        }
        
        uiInteractionLogFile = File(uiUserTaskDir, "ui_interaction_log_$timestamp.json")
        uiInteractions.clear()
        
        Log.d(TAG, "UI interaction log file initialized: "+uiInteractionLogFile.absolutePath)
    }

    // 添加设置用户ID和任务ID的方法
    fun setUserAndTask(userId: String, taskId: String) {
        this.userId = userId
        this.taskId = taskId
        // 重新初始化日志目录
        initializeLogDirectories()
        Log.d(TAG, "用户ID和任务ID已更新: 用户=$userId, 任务=$taskId")
        // 发送ROLE信号
        sendPCSignal("ROLE", mapOf("PID" to userId, "TaskID" to taskId))
    }

    private fun logSpokenText(text: String) {
        val timestamp = SimpleDateFormat("MM-dd HH:mm:ss", Locale.getDefault()).format(Date())
        val logEntry = "$timestamp: $text\n"
        try {
            FileWriter(logFile, true).use { writer ->
                writer.append(logEntry)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error writing to log file: ${e.message}")
        }
    }

    private fun installLanguageData() {
        Log.d(TAG, "Attempting to install language data")
        val installIntent = Intent()
        installIntent.action = TextToSpeech.Engine.ACTION_INSTALL_TTS_DATA
        installIntent.flags = Intent.FLAG_ACTIVITY_NEW_TASK
        startActivity(installIntent)
    }

    private fun retryInitialization() {
        Log.d(TAG, "Retrying TTS initialization")
        Handler(Looper.getMainLooper()).postDelayed({
            // This logic should be in TtsManager. If it's here, TtsManager is not fully integrated.
            // For now, assuming this is removed or handled by TtsManager.
            // tts?.shutdown() 
            // tts = null
            // initializeTTS() 
            Log.w(TAG, "retryInitialization called in ScreenReaderService, should be in TtsManager")
        }, 3000)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        if (!isServiceActive) return
        // Log.d(TAG, "Received accessibility event: ${eventTypeToString(event.eventType)}")
        val eventText = event.text.joinToString(" ")
        when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_CLICKED -> {
                Log.d(TAG, "Click event detected: $eventText")
                speakOut("Clicked: $eventText")
                // 标记需要更新缓存
                needUpdateCache = true
                // 获取上一个焦点位置
                val lastFocusRect = focusOverlayView.getFocusRect()
                // 找到最近的可聚焦虚拟节点
                val nearestVNode = lastFocusRect?.let { findNearestVirtualNode(it.centerX().toFloat(), it.centerY().toFloat()) }
                updateFocusOverlay(event)
                if (nearestVNode != null) {
                    updateFocusAndSpeak(nearestVNode)
                } else {
                    Log.d(TAG, "No nearest focusable virtual node found, updating focus overlay")
                    updateFocusOverlay(event)
                }
            }
            AccessibilityEvent.TYPE_VIEW_SELECTED-> {
            }
            AccessibilityEvent.TYPE_VIEW_SCROLLED-> {
                // 滚动后视图变化，需要更新缓存
                needUpdateCache = true
            }
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> {
                // 先记录内容变化的日志
                logWindowContentChange(event)
                // 检查是否是系统UI区域的变化，并且不是由双击触发的
                if (!isSystemUIEvent(event) && !isDoubleClickAction) {
                    // 内容变化，需要更新缓存
                    needUpdateCache = true
                    // 取消之前的延迟任务（如果有的话）
                    handler.removeCallbacksAndMessages(null)
                    // 延迟3秒后执行captureAndSaveUIElements
                    handler.postDelayed({
                        captureAndSaveUIElements()
                        // 新增：通过socket通知PC
                        notifyPCUiUpdated()
                        // === 虚拟树重建 ===
                        buildVirtualTree()
                    }, 2000) // 2000毫秒 = 2秒
                }
                // TODO: 在此处集成虚拟树导航与聚焦逻辑
            }
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                // 窗口状态变化，一定要更新缓存
                needUpdateCache = true
                // 获取上一个焦点位置
                val lastFocusRect = focusOverlayView.getFocusRect()
                // 找到最近的可聚焦虚拟节点
                val nearestVNode = lastFocusRect?.let { findNearestVirtualNode(it.centerX().toFloat(), it.centerY().toFloat()) }
                if (nearestVNode != null) {
                    updateFocusAndSpeak(nearestVNode)
                } else {
                    Log.d(TAG, "No nearest focusable virtual node found, updating focus overlay")
                    updateFocusOverlay(event)
                }
                // === 虚拟树重建 ===
                buildVirtualTree()
                // TODO: 在此处集成虚拟树导航与聚焦逻辑
            }
            AccessibilityEvent.TYPE_VIEW_FOCUSED -> {
                // 无需特殊处理
            }
        }
    }

    private fun logWindowContentChange(event: AccessibilityEvent) {
        if (event.text.isNotEmpty()) {
            val changeTypes = event.contentChangeTypes
            val changeTypeDescriptions = mutableListOf<String>()

            if (changeTypes and AccessibilityEvent.CONTENT_CHANGE_TYPE_CONTENT_DESCRIPTION != 0) {
                changeTypeDescriptions.add("Content Description")
            }
            if (changeTypes and AccessibilityEvent.CONTENT_CHANGE_TYPE_TEXT != 0) {
                changeTypeDescriptions.add("Text")
            }
            if (changeTypes and AccessibilityEvent.CONTENT_CHANGE_TYPE_SUBTREE != 0) {
                changeTypeDescriptions.add("Subtree")
            }
            if (changeTypes and AccessibilityEvent.CONTENT_CHANGE_TYPE_UNDEFINED != 0) {
                changeTypeDescriptions.add("Undefined")
            }

            // 只有在调试模式下才记录日志
            if (DEBUG) {
                val changeTypeString = if (changeTypeDescriptions.isNotEmpty()) {
                    changeTypeDescriptions.joinToString(", ")
                } else {
                    "Unknown"
                }
                
                Log.d(TAG, "Content change: ${event.text}, type: $changeTypeString")
            }
        }
    }

    private fun findNearestFocusableNode(lastFocusRect: Rect?): AccessibilityNodeInfo? {
        if (lastFocusRect == null) return null
        
        val root = rootInActiveWindow ?: return null
        val allNodes = getAllNodes(root)
        var nearestNode: AccessibilityNodeInfo? = null
        var minDistance = Double.MAX_VALUE
        
        // 获取状态栏高度
        val statusBarHeight = getStatusBarHeight()
        // Log.d(TAG, "Status bar height: $statusBarHeight")

        for (node in allNodes) {
            if (node.isVisibleToUser && isNodeAccessible(node)) {
                val rect = Rect()
                node.getBoundsInScreen(rect)
                
                // 排除状态栏中的元素
                if (rect.top < statusBarHeight) {
                    // Log.d(TAG, "Skipping node in status bar: ${getNodeDescription(node)}")
                    continue
                }
                
                val distance = calculateDistance(lastFocusRect, rect)
                val nodeName = getNodeDescription(node)
                // Log.d(TAG, "Node: $nodeName, Distance: $distance")
                
                if (distance < minDistance) {
                    minDistance = distance
                    nearestNode = node
                }
            }
        }
        
        Log.d(TAG, "Nearest node: ${nearestNode?.let { getNodeDescription(it) }}, Distance: $minDistance")
        return nearestNode
    }

    private fun calculateDistance(rect1: Rect, rect2: Rect): Double {
        val x1 = rect1.centerX()
        val y1 = rect1.centerY()
        val x2 = rect2.centerX()
        val y2 = rect2.centerY()
        return Math.sqrt(((x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1)).toDouble())
    }

    private fun logUIInteraction(node: AccessibilityNodeInfo) {
        val windowInfo = getWindowInfo()
        val rect = Rect()
        node.getBoundsInScreen(rect)
        val centerX = (rect.left + rect.right) / 2
        val centerY = (rect.top + rect.bottom) / 2

        // 使用 viewIdResourceName 和坐标作为键
        val elementId = if (node.viewIdResourceName != null) {
            "${node.viewIdResourceName}:$centerX,$centerY"
        } else {
            "element_${System.identityHashCode(node)}:$centerX,$centerY"
        }

        val windowInteractions = uiInteractions.getOrPut(windowInfo.first) { JSONObject() }
        val elementInteraction = windowInteractions.optJSONObject(elementId) ?: JSONObject()

        elementInteraction.put("name", getNodeDescriptionAll(node))
        elementInteraction.put("text", node.text?.toString() ?: "")
        elementInteraction.put("contentDescription", node.contentDescription?.toString() ?: "")

        // 如果 text 和 contentDescription 都为空,添加 childName
        if ((node.text == null || node.text.isBlank()) && 
            (node.contentDescription == null || node.contentDescription.isBlank())) {
            val childName = findChildDescription(node)
            if (childName.isNotBlank()) {
                elementInteraction.put("childName", childName)
            }
        }

        elementInteraction.put("position", JSONObject().apply {
            put("x", centerX)
            put("y", centerY)
        })

        // 更新访问记录
        val visitRecords = elementInteraction.optJSONArray("visitRecords") ?: JSONArray()
        val currentTime = System.currentTimeMillis()

        if (lastVisitedElement != elementId) {
            // 结束上一次访问（如果有的话）
            if (lastVisitedElement != null) {
                updateLastVisitRecord(windowInteractions, lastVisitedElement!!, currentTime)
            }

            // 开始新的访问记录
            val newVisit = JSONObject().apply {
                put("startTime", ISO8601Utils.format(Date(currentTime)))
                put("navigationPath", JSONArray().apply {
                    put(JSONObject().apply {
                        put("previousElement", lastVisitedElement)
                        put("currentElement", elementId)
                        put("timeSpent", 0) // 将在离开此元素时更新，以毫秒为单位
                    })
                })
            }
            visitRecords.put(newVisit)
            visitStartTime = currentTime
        }

        elementInteraction.put("visitRecords", visitRecords)
        windowInteractions.put(elementId, elementInteraction)
        uiInteractions[windowInfo.first] = windowInteractions

        lastVisitedElement = elementId
        saveUIInteractionsToFile()
    }

    private fun findChildDescription(node: AccessibilityNodeInfo): String {
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val childDescription = when {
                !child.text.isNullOrBlank() -> child.text.toString()
                !child.contentDescription.isNullOrBlank() -> child.contentDescription.toString()
                else -> findChildDescription(child)
            }
            if (childDescription.isNotBlank()) {
                child.recycle()
                return childDescription
            }
            child.recycle()
        }
        return ""
    }

    private fun updateLastVisitRecord(windowInteractions: JSONObject, elementId: String, endTime: Long) {
        val elementInteraction = windowInteractions.optJSONObject(elementId) ?: return
        val visitRecords = elementInteraction.optJSONArray("visitRecords") ?: return
        val lastVisit = visitRecords.optJSONObject(visitRecords.length() - 1) ?: return

        lastVisit.put("endTime", ISO8601Utils.format(Date(endTime)))
        val navigationPath = lastVisit.optJSONArray("navigationPath")
        val lastPath = navigationPath?.optJSONObject(navigationPath.length() - 1)
        lastPath?.put("timeSpent", endTime - visitStartTime) // 以毫秒为单位记录时间差
    }

    private fun getWindowInfo(): Pair<String, String> {
        val root = rootInActiveWindow
        val windowId = root?.windowId?.toString() ?: "unknown"
        val windowName = root?.className?.toString() ?: "unknown"
        root?.recycle()
        return Pair(windowId, windowName)
    }

    private fun saveUIInteractionsToFile() {
        try {
            val jsonObject = JSONObject()
            jsonObject.put("userId", userId)
            jsonObject.put("taskId", taskId)
            jsonObject.put("timestamp", SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.getDefault()).format(Date()))
            
            val windowsJson = JSONObject()
            for ((windowId, interactions) in uiInteractions) {
                val windowInfo = JSONObject()
                windowInfo.put("name", getWindowInfo().second)
                windowInfo.put("elements", interactions)
                windowsJson.put(windowId, windowInfo)
            }
            
            jsonObject.put("windows", windowsJson)
            
            FileWriter(uiInteractionLogFile).use { writer ->
                writer.write(jsonObject.toString(4))  // 使用 4 个空格进行缩进
            }
            Log.d(TAG, "UI interactions saved to: ${uiInteractionLogFile.absolutePath}")
        } catch (e: Exception) {
            Log.e(TAG, "Error writing UI interactions to file: ${e.message}")
        }
    }

    private fun getElementId(node: AccessibilityNodeInfo): String {
        return node.viewIdResourceName ?: "${node.className}_${node.text}_${node.contentDescription}"
    }

    private fun getNodeDescription(node: AccessibilityNodeInfo): String {
        // 现有的逻辑保持不变
        val text = node.text
        if (!text.isNullOrBlank()) {
            return text.toString()
        }

        val contentDescription = node.contentDescription
        if (!contentDescription.isNullOrBlank()) {
            return contentDescription.toString()
        }

        // 如果当前节点没有描述，收集所有不可聚焦子节点的内容
        return collectAllChildrenDescriptions(node)
    }

    private fun searchDescriptionInChildren(node: AccessibilityNodeInfo): String {
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val childDescription = getNodeDescription(child)
            if (childDescription != "Unnamed element") {
                child.recycle()  // 重要：记得回收不再使用的 AccessibilityNodeInfo 对象
                return childDescription
            }
            child.recycle()
        }
        return "Unnamed element"  // 如果所有子节点都没有找到描述，则返回默认值
    }
    
    // 新增方法：收集所有不可聚焦子节点的描述
    private fun collectAllChildrenDescriptions(node: AccessibilityNodeInfo): String {
        val descriptions = mutableListOf<String>()
        collectDescriptionsRecursively(node, descriptions, HashSet())
        
        return if (descriptions.isEmpty()) {
            "Unnamed element"
        } else {
            descriptions.joinToString(", ")
        }
    }
    
    // 递归收集所有子节点的描述
    private fun collectDescriptionsRecursively(node: AccessibilityNodeInfo, descriptions: MutableList<String>, visitedNodes: HashSet<Int>) {
        // 防止循环引用导致的无限递归
        val nodeHash = System.identityHashCode(node)
        if (visitedNodes.contains(nodeHash)) {
            return
        }
        visitedNodes.add(nodeHash)
        
        // 遍历所有子节点
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            
            // 如果子节点可以聚焦，则跳过（因为这些节点会单独被朗读）
            if (child.isFocusable) {
                child.recycle()
                continue
            }
            
            // 获取子节点的描述
            val childText = child.text?.toString()
            val childContentDesc = child.contentDescription?.toString()
            
            // 如果子节点有描述，则添加到列表中
            if (!childText.isNullOrBlank()) {
                descriptions.add(childText)
            } else if (!childContentDesc.isNullOrBlank()) {
                descriptions.add(childContentDesc)
            } else {
                // 如果子节点没有描述，则递归检查其子节点
                collectDescriptionsRecursively(child, descriptions, visitedNodes)
            }
            
            child.recycle()
        }
    }

    private fun getNodeDescriptionAll(node: AccessibilityNodeInfo): String {
        return node.text?.toString()
            ?: node.contentDescription?.toString()
            ?: node.viewIdResourceName
            ?: node.className?.toString()
            ?: "Unnamed element"
    }

    private fun captureAndSaveUIElements() {
        val root = rootInActiveWindow ?: return
        val uiElements = JSONObject()
        traverseUIHierarchy(root, uiElements)
        val timestamp = SimpleDateFormat("MMddHHmmss", Locale.getDefault()).format(Date())
        val uiElementsLogFile = File(uiElementsLogDir, "ui_elements_log_${timestamp}.json")
        val jsonObject = JSONObject()
        jsonObject.put("timestamp", timestamp)
        jsonObject.put("elements", uiElements)
        try {
            FileWriter(uiElementsLogFile).use { writer ->
                writer.write(jsonObject.toString(4))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error writing UI elements to file: "+e.message)
        }
        // 保存虚拟树，结构一致
        if (virtualRoot != null) {
            val virtualTreeJson = serializeVirtualNodeUnified(virtualRoot)
            val virtualTreeLogFile = File(uiElementsLogDir, "virtual_tree_log_${timestamp}.json")
            try {
                FileWriter(virtualTreeLogFile).use { writer ->
                    if (virtualTreeJson != null) {
                        writer.write(virtualTreeJson.toString(4))
                    } else {
                        writer.write("{}")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error writing virtual tree to file: "+e.message)
            }
        }
        root.recycle()
    }

    private fun traverseUIHierarchy(node: AccessibilityNodeInfo, jsonObject: JSONObject, parentId: String? = null) {
        val rect = Rect()
        node.getBoundsInScreen(rect)
        val id = generateElementHashId(node.viewIdResourceName, node.className, rect)
        val centerX = (rect.left + rect.right) / 2
        val centerY = (rect.top + rect.bottom) / 2
        val childrenMap = mutableMapOf<String, JSONObject>()
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val childRect = Rect()
            child.getBoundsInScreen(childRect)
            val childId = generateElementHashId(child.viewIdResourceName, child.className, childRect)
            val childJson = JSONObject()
            traverseUIHierarchy(child, childJson, id)
            childrenMap[childId] = childJson.getJSONObject(childId)
            child.recycle()
        }
        val nodeJson = serializeNodeUnified(
            id = id,
            parentId = parentId,
            type = null, // ui_elements_log不需要type
            canFocus = null, // ui_elements_log不需要canFocus
            text = node.text,
            contentDescription = node.contentDescription,
            viewIdResourceName = node.viewIdResourceName,
            className = node.className,
            isClickable = node.isClickable,
            isCheckable = node.isCheckable,
            isChecked = node.isChecked,
            isFocusable = node.isFocusable,
            isEnabled = node.isEnabled,
            isPassword = node.isPassword,
            isSelected = node.isSelected,
            bounds = rect,
            center = Pair(centerX, centerY),
            children = childrenMap
        )
        jsonObject.put(id, nodeJson)
    }

    private fun serializeNodeUnified(
        id: String,
        parentId: String?,
        type: String?,
        canFocus: Boolean?,
        text: CharSequence?,
        contentDescription: CharSequence?,
        viewIdResourceName: String?,
        className: CharSequence?,
        isClickable: Boolean,
        isCheckable: Boolean,
        isChecked: Boolean,
        isFocusable: Boolean,
        isEnabled: Boolean,
        isPassword: Boolean,
        isSelected: Boolean,
        bounds: Rect,
        center: Pair<Int, Int>,
        children: Map<String, JSONObject>
    ): JSONObject {
        val json = JSONObject()
        json.put("id", id)
        if (type != null) json.put("type", type)
        if (canFocus != null) json.put("canFocus", canFocus)
        json.put("text", text?.toString())
        json.put("contentDescription", contentDescription?.toString())
        json.put("viewIdResourceName", viewIdResourceName)
        json.put("className", className?.toString())
        json.put("isClickable", isClickable)
        json.put("isCheckable", isCheckable)
        json.put("isChecked", isChecked)
        json.put("isFocusable", isFocusable)
        json.put("isEnabled", isEnabled)
        json.put("isPassword", isPassword)
        json.put("isSelected", isSelected)
        val boundsJson = JSONObject()
        boundsJson.put("left", bounds.left)
        boundsJson.put("top", bounds.top)
        boundsJson.put("right", bounds.right)
        boundsJson.put("bottom", bounds.bottom)
        json.put("bounds", boundsJson)
        val centerJson = JSONObject()
        centerJson.put("x", center.first)
        centerJson.put("y", center.second)
        json.put("center", centerJson)
        json.put("parentId", parentId)
        val childrenJson = JSONObject()
        for ((k, v) in children) {
            childrenJson.put(k, v)
        }
        json.put("children", childrenJson)
        return json
    }

    private fun serializeVirtualNodeUnified(node: VirtualNode?, parentId: String? = null): JSONObject? {
        if (node == null) return null
        val childrenMap = mutableMapOf<String, JSONObject>()
        for (child in node.children) {
            val childJson = serializeVirtualNodeUnified(child, node.id)
            if (childJson != null) {
                childrenMap[child.getIdForLog()] = childJson
            }
        }
        return serializeNodeUnified(
            id = node.getIdForLog(),
            parentId = parentId,
            type = node.type.toString(),
            canFocus = node.canFocus,
            text = node.text,
            contentDescription = node.contentDescription,
            viewIdResourceName = node.viewIdResourceName,
            className = node.className,
            isClickable = node.isClickable,
            isCheckable = node.isCheckable,
            isChecked = node.isChecked,
            isFocusable = node.isFocusable,
            isEnabled = node.isEnabled,
            isPassword = node.isPassword,
            isSelected = node.isSelected,
            bounds = node.bounds,
            center = node.center,
            children = childrenMap
        )
    }

    private fun VirtualNode.getIdForLog(): String {
        return generateElementHashId(this.viewIdResourceName, this.className, this.bounds)
    }

    private fun updateFocusOverlay(event: AccessibilityEvent) {
        // Log.d(TAG, "updateFocusOverlay called with event type: ${eventTypeToString(event.eventType)}")
        val node = event.source ?: rootInActiveWindow
        if (node == null) {
            Log.e(TAG, "Both event source and root window are null, cannot update focus overlay")
            focusOverlayView.updateFocusRect(null)
            return
        }

        // Log.d(TAG, "Node details: class=${node.className}, package=${node.packageName}")

        val rect = Rect()
        node.getBoundsInScreen(rect)

        // 获取状态栏高度
        val resourceId = resources.getIdentifier("status_bar_height", "dimen", "android")
        val statusBarHeight = if (resourceId > 0) {
            resources.getDimensionPixelSize(resourceId)
        } else {
            0
        }

        // 获取导航栏高度
        val navBarHeight = getNavigationBarHeight()

        // Log.d(TAG, "UI Element: ${getNodeDescription(node)}")
        // Log.d(TAG, "Original rect: $rect")
        // Log.d(TAG, "Status bar height: $statusBarHeight")
        // Log.d(TAG, "Navigation bar height: $navBarHeight")

        // 调整矩形坐标
        val adjustedRect = adjustCoordinates(rect)
        // Log.d(TAG, "Adjusted rect: $adjustedRect")

        // 检查矩形是否有效
        if (adjustedRect.isEmpty || adjustedRect.left < 0 || adjustedRect.top < 0 || adjustedRect.right <= adjustedRect.left || adjustedRect.bottom <= adjustedRect.top) {
            // Log.w(TAG, "Invalid focus rectangle: $adjustedRect")
            // 尝试获取父节点的边界
            val parent = node.parent
            if (parent != null) {
                parent.getBoundsInScreen(adjustedRect)
                adjustedRect.top -= statusBarHeight
                adjustedRect.bottom -= statusBarHeight
                // Log.d(TAG, "Using parent rect: $adjustedRect")
            }
        }

        // Log.d(TAG, "Final focus overlay rect: $adjustedRect")
        focusOverlayView.updateFocusRect(adjustedRect)

        // 回收 AccessibilityNodeInfo 对象
        node.recycle()
    }

    private fun getNavigationBarHeight(): Int {
        val resources = resources
        val resourceId = resources.getIdentifier("navigation_bar_height", "dimen", "android")
        return if (resourceId > 0) {
            resources.getDimensionPixelSize(resourceId)
        } else {
            0
        }
    }

    // speakOut should be handled by TtsManager
    private fun speakOut(text: String) {
        if(::ttsManager.isInitialized) {
            ttsManager.speakOut(text, handler)
        } else {
            Log.e(TAG, "TtsManager not initialized, cannot speak: $text")
            // Fallback or re-initialize TtsManager if necessary
        }
    }

    override fun onInterrupt() {
        if (isServiceActive) {
            Log.d(TAG, "ScreenReaderService interrupted")
        }
    }

    override fun onDestroy() {
        if (isServiceActive) {
            try {
                // Update the last visited element's end time
                if (lastVisitedElement != null) {
                    val windowInfo = getWindowInfo()
                    val windowInteractions = uiInteractions[windowInfo.first]
                    if (windowInteractions != null) {
                        updateLastVisitRecord(windowInteractions, lastVisitedElement!!, System.currentTimeMillis())
                    }
                }
                saveUIInteractionsToFile()
                Log.d(TAG, "UI interactions saved successfully on service destroy")
            } catch (e: Exception) {
                Log.e(TAG, "Error saving UI interactions on service destroy: ${e.message}")
            }
            
            // 清理资源
            tts?.shutdown()
            windowManager.removeView(focusOverlayView)
            (getSystemService(WINDOW_SERVICE) as WindowManager).removeView(overlayView)
            
            // 重置服务状态
            isServiceActive = false
        }
        super.onDestroy()
        Log.d(TAG, "ScreenReaderService destroyed")
        
        // 移除所有待执行的回调
        handler.removeCallbacksAndMessages(null)
    }

    private fun performClick(x: Float, y: Float) {
        Log.d(TAG, "Performing click at ($x, $y)")
        
        // 尝试找到点击位置的节点
        val node = findNodeAtPosition(x.toInt(), y.toInt())
        
        if (node != null) {
            // 如果找到了节点，使用 performAction
            val clickResult = node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            Log.d(TAG, "performAction result: $clickResult")
            if (clickResult) {
                Log.d(TAG, "Click action performed successfully")
                speakOut("Clicked")
                Log.d(TAG, "Spoke out: Clicked")
            } else {
                Log.e(TAG, "Failed to perform click action")
                speakOut("Click failed")
                Log.e(TAG, "Spoke out: Click failed")
            }
            node.recycle()
        } else {
            Log.e(TAG, "No node found at position ($x, $y)")
            speakOut("No clickable item found")
            Log.e(TAG, "Spoke out: No clickable item found")
        }
    }

    private fun findNodeAtPosition(x: Int, y: Int): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        
        // 获取状态栏高度
        val statusBarHeight = getStatusBarHeight()
        // 调整y坐标以考虑状态栏
        val adjustedY = y + statusBarHeight
        
        // 查找当前活跃的视图层级（如浮窗）
        val activeViewHierarchy = findActiveViewHierarchy(root)
        
        // 如果找到活跃视图层级，优先在其中查找节点
        if (activeViewHierarchy != null) {
            val nodeInActiveHierarchy = findNodeAtPositionRecursive(activeViewHierarchy, x, adjustedY)
            if (nodeInActiveHierarchy != null) {
                return nodeInActiveHierarchy
            }
        }
        
        // 如果在活跃视图层级中没有找到节点，或者没有活跃视图层级，则在整个视图树中查找
        return findNodeAtPositionRecursive(root, x, adjustedY)
    }

    private fun findNodeAtPositionRecursive(
        node: AccessibilityNodeInfo,
        x: Int,
        y: Int
    ): AccessibilityNodeInfo? {
        val rect = Rect()
        node.getBoundsInScreen(rect)
        
        if (rect.contains(x, y)) {
            if (isViewGroup(node)) {
                // 对于ViewGroup，倒序遍历子节点
                for (i in node.childCount - 1 downTo 0) {
                    val child = node.getChild(i) ?: continue
                    val result = findNodeAtPositionRecursive(child, x, y)
                    if (result != null) {
                        return result
                    }
                    child.recycle()
                }
            } else {
                // 对于非ViewGroup，正序遍历子节点
                for (i in 0 until node.childCount) {
                    val child = node.getChild(i) ?: continue
                    val result = findNodeAtPositionRecursive(child, x, y)
                    if (result != null) {
                        return result
                    }
                    child.recycle()
                }
            }
            
            // 如果没有找到合适的子节点，且当前节点是可访问的，则返回当前节点
            if (isNodeAccessible(node)) {
                return node
            }
        }
        
        return null
    }

    private fun performScroll(distanceX: Float, distanceY: Float) {
        val scrollableNode = findScrollableNode(rootInActiveWindow)
        if (scrollableNode != null) {
            val scrollResult = if (distanceY > 0) {
                scrollableNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
            } else {
                scrollableNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
            }
            if (scrollResult) {
                Log.d(TAG, "Scroll action performed successfully")
                speakOut("Scrolled")
            } else {
                Log.e(TAG, "Failed to perform scroll action")
                performScrollSystem(distanceY)
            }
            scrollableNode.recycle()
        } else {
            Log.d(TAG, "No scrollable node found, performing system scroll")
            performScrollSystem(distanceY)
        }
    }

    private fun moveFocusToNext() {
        // 确保缓存是最新的
        // ensureCacheUpdated()
        
        val currentIndex = cachedFocusableNodes.indexOf(currentFocusedNode)
        if (currentIndex >= 0 && currentIndex < cachedFocusableNodes.size - 1) {
            val nextNode = cachedFocusableNodes[currentIndex + 1]
            // 先在虚拟树中查找对应的虚拟节点
            val virtualNode = findVirtualNodeForRealNode(nextNode)
            if (virtualNode != null) {
                updateFocusAndSpeak(virtualNode)
            } else {
                // 如果找不到，使用通用处理方法
                handleRealNodeFocus(nextNode)
            }
        } else {
            speakOut("No more focusable elements")
        }
    }

    private fun moveFocusToPrevious() {
        // 确保缓存是最新的
        // ensureCacheUpdated()
        
        val currentIndex = cachedFocusableNodes.indexOf(currentFocusedNode)
        if (currentIndex > 0) {
            val prevNode = cachedFocusableNodes[currentIndex - 1]
            // 先在虚拟树中查找对应的虚拟节点
            val virtualNode = findVirtualNodeForRealNode(prevNode)
            if (virtualNode != null) {
                updateFocusAndSpeak(virtualNode)
            } else {
                // 如果找不到，使用通用处理方法
                handleRealNodeFocus(prevNode)
            }
        } else {
            speakOut("No previous focusable elements")
        }
    }

    private fun logNodeDetails(node: AccessibilityNodeInfo?) {
        node?.let {
            Log.d(TAG, "  Text: ${it.text}")
            Log.d(TAG, "  Content Description: ${it.contentDescription}")
            Log.d(TAG, "  Class Name: ${it.className}")
            Log.d(TAG, "  View ID Resource Name: ${it.viewIdResourceName}")
            Log.d(TAG, "  Package Name: ${it.packageName}")
        } ?: Log.d(TAG, "  Node is null")
    }

    private fun findNextFocusableNode(currentNode: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (currentNode == null) {
            return findFirstAccessibleNode(rootInActiveWindow)
        }

        // 查找当前活跃的视图层级
        val activeViewHierarchy = findActiveViewHierarchy(rootInActiveWindow)
        
        // 获取所有节点
        val root = rootInActiveWindow ?: return null
        val allNodes = getAllNodes(root)
        
        // 确定当前节点是否在活跃视图层级中
        var isCurrentNodeInActiveHierarchy = false
        if (activeViewHierarchy != null) {
            isCurrentNodeInActiveHierarchy = isNodeInHierarchy(currentNode, activeViewHierarchy)
        }
        
        // 获取当前节点在所有节点中的索引
        val currentIndex = allNodes.indexOf(currentNode)
        
        // 如果当前节点在活跃视图层级中，首先在活跃视图层级内查找下一个节点
        if (isCurrentNodeInActiveHierarchy) {
            for (i in currentIndex + 1 until allNodes.size) {
                val node = allNodes[i]
                val isAccessible = isNodeAccessible(node)
                val isWithinScreen = isNodeWithinScreen(node)
                val isInActiveHierarchy = isNodeInHierarchy(node, activeViewHierarchy)
                
                if (isInActiveHierarchy && isAccessible && isWithinScreen) {
                    return node
                }
            }
        }
        
        // 如果当前节点不在活跃视图层级中，或者在活跃视图层级中没有找到下一个节点
        // 尝试在所有节点中找到下一个节点（普通视图层级中的）
        for (i in currentIndex + 1 until allNodes.size) {
            val node = allNodes[i]
            val isAccessible = isNodeAccessible(node)
            val isWithinScreen = isNodeWithinScreen(node)
            val isInActiveHierarchy = activeViewHierarchy != null && isNodeInHierarchy(node, activeViewHierarchy)
            
            // 首先查找非活跃视图层级中的节点
            if (isAccessible && isWithinScreen) {
                // 如果当前节点已经不在活跃视图层级中，或者我们确认已经需要过渡到普通视图层级
                if (!isInActiveHierarchy || !isCurrentNodeInActiveHierarchy) {
                    return node
                }
            }
        }
        
        // 如果仍然没有找到下一个节点，尝试在整个层级中查找
        if (currentIndex < allNodes.size - 1) {
            for (i in currentIndex + 1 until allNodes.size) {
                val node = allNodes[i]
                if (isNodeAccessible(node) && isNodeWithinScreen(node)) {
                    return node
                }
            }
        }
        
        return null
    }

    // 精简活跃视图层级查找方法的日志输出
    private fun findActiveViewHierarchy(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null
        
        // 策略1: 查找是否有浮窗或对话框类视图
        // 通常浮窗/对话框有特定的类名或者在屏幕中央有较高的Z轴值
        if (isViewGroup(root)) {
            // 对ViewGroup类型的节点进行倒序遍历
            for (i in root.childCount - 1 downTo 0) {
                val child = root.getChild(i) ?: continue
                
                val className = child.className?.toString() ?: ""
                // 根据类名识别对话框、浮窗等UI元素
                if (className.contains("Dialog") || 
                    className.contains("Popup") || 
                    className.contains("Modal") ||
                    className.contains("AlertDialog") ||
                    className.contains("BottomSheet")) {
                    
                    return child
                }
                
                // 递归检查子视图
                val activeInChild = findActiveViewHierarchy(child)
                if (activeInChild != null) {
                    child.recycle()
                    return activeInChild
                }
                
                child.recycle()
            }
        } else {
            // 对非ViewGroup类型的节点进行正序遍历
            for (i in 0 until root.childCount) {
                val child = root.getChild(i) ?: continue
                
                val className = child.className?.toString() ?: ""
                // 根据类名识别对话框、浮窗等UI元素
                if (className.contains("Dialog") || 
                    className.contains("Popup") || 
                    className.contains("Modal") ||
                    className.contains("AlertDialog") ||
                    className.contains("BottomSheet")) {
                    
                    return child
                }
                
                // 递归检查子视图
                val activeInChild = findActiveViewHierarchy(child)
                if (activeInChild != null) {
                    child.recycle()
                    return activeInChild
                }
                
                child.recycle()
            }
        }
        
        // 策略2: 如果没有找到特定类名的浮窗，查找屏幕中央有元素的视图
        // 浮窗通常位于屏幕中央
        if (isViewGroup(root)) {
            // 对ViewGroup类型的节点进行倒序遍历
            for (i in root.childCount - 1 downTo 0) {
                val child = root.getChild(i) ?: continue
                
                // 获取视图在屏幕上的位置
                val rect = Rect()
                child.getBoundsInScreen(rect)
                
                // 判断视图是否在屏幕中央
                val isCentral = isCentralOnScreen(rect)
                if (isCentral && hasInteractiveElements(child)) {
                    return child
                }
                
                child.recycle()
            }
        } else {
            // 对非ViewGroup类型的节点进行正序遍历
            for (i in 0 until root.childCount) {
                val child = root.getChild(i) ?: continue
                
                // 获取视图在屏幕上的位置
                val rect = Rect()
                child.getBoundsInScreen(rect)
                
                // 判断视图是否在屏幕中央
                val isCentral = isCentralOnScreen(rect)
                if (isCentral && hasInteractiveElements(child)) {
                    return child
                }
                
                child.recycle()
            }
        }
        
        // 如果没有找到特定的活跃视图，返回null
        return null
    }

    private fun findPreviousFocusableNode(currentNode: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (currentNode == null) return null
        
        val root = rootInActiveWindow ?: return null
        
        // 查找当前活跃的视图层级
        val activeViewHierarchy = findActiveViewHierarchy(root)
        
        // 首先获取所有节点，方便后续查找
        val allNodes = getAllNodes(root)
        
        // 如果当前节点在活跃视图层级中，尝试在活跃视图层级内查找前一个节点
        var isCurrentNodeInActiveHierarchy = false
        if (activeViewHierarchy != null) {
            isCurrentNodeInActiveHierarchy = isNodeInHierarchy(currentNode, activeViewHierarchy)
        }
        
        // 获取当前节点的索引
        val currentIndex = allNodes.indexOf(currentNode)
        
        // 如果我们已经在活跃视图层级中，首先在活跃视图层级内查找
        if (isCurrentNodeInActiveHierarchy) {
            // 在所有节点中向前查找同样在活跃视图层级中的节点
            for (i in currentIndex - 1 downTo 0) {
                val node = allNodes[i]
                val isAccessible = isNodeAccessible(node)
                val isWithinScreen = isNodeWithinScreen(node)
                val isInActiveHierarchy = isNodeInHierarchy(node, activeViewHierarchy)
                
                if (isInActiveHierarchy && isAccessible && isWithinScreen) {
                    return node
                }
            }
        }
        
        // 如果当前节点不在活跃视图层级中，或者在活跃视图层级中没有找到前一个节点
        // 那么在所有节点中查找非活跃视图层级的节点
        for (i in currentIndex - 1 downTo 0) {
            val node = allNodes[i]
            val isAccessible = isNodeAccessible(node)
            val isWithinScreen = isNodeWithinScreen(node)
            val isInActiveHierarchy = activeViewHierarchy != null && isNodeInHierarchy(node, activeViewHierarchy)
            
            // 首先查找非活跃视图层级中的节点
            if (isAccessible && isWithinScreen) {
                // 在活跃视图层级外查找，或者当我们确认已经回到了普通视图层级
                if (!isInActiveHierarchy || !isCurrentNodeInActiveHierarchy) {
                    return node
                }
            }
        }
        
        // 如果还是没有找到，尝试在整个层级中查找
        if (currentIndex > 0) {
            for (i in currentIndex - 1 downTo 0) {
                val node = allNodes[i]
                if (isNodeAccessible(node) && isNodeWithinScreen(node)) {
                    return node
                }
            }
        }
        
        return null
    }

    private fun getAllNodes(node: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        val nodes = mutableListOf<AccessibilityNodeInfo>()
        addNodeAndChildrenSmartOrder(node, nodes)
        return nodes
    }

    // 新添加的方法，根据节点类型决定遍历顺序
    private fun addNodeAndChildrenSmartOrder(node: AccessibilityNodeInfo, nodes: MutableList<AccessibilityNodeInfo>) {
        nodes.add(node)
        
        if (isViewGroup(node)) {
            // 对于ViewGroup，倒序遍历子节点
            for (i in node.childCount - 1 downTo 0) {
                val child = node.getChild(i) ?: continue
                addNodeAndChildrenSmartOrder(child, nodes)
            }
        } else {
            // 对于非ViewGroup，正序遍历子节点
            for (i in 0 until node.childCount) {
                val child = node.getChild(i) ?: continue
                addNodeAndChildrenSmartOrder(child, nodes)
            }
        }
    }

    // 添加 findScrollableNode 方法
    private fun findScrollableNode(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null
        if (root.isScrollable) return root
        for (i in 0 until root.childCount) {
            val child = root.getChild(i)
            val scrollable = findScrollableNode(child)
            if (scrollable != null) {
                return scrollable
            }
            child.recycle()
        }
        return null
    }

    // 修改 performScrollSystem 方法
    private fun performScrollSystem(distanceY: Float) {
        val scrollUp = distanceY > 0
        val scrollPath = Path()
        val displayMetrics = resources.displayMetrics
        val screenHeight = displayMetrics.heightPixels
        val screenWidth = displayMetrics.widthPixels

        val startY = if (scrollUp) screenHeight * 0.8f else screenHeight * 0.2f
        val endY = if (scrollUp) screenHeight * 0.2f else screenHeight * 0.8f

        scrollPath.moveTo(screenWidth / 2f, startY)
        scrollPath.lineTo(screenWidth / 2f, endY)
        
        Log.d(TAG, "Initiating system scroll: direction=${if (scrollUp) "up" else "down"}, start=$startY, end=$endY")
        
        val scrollBuilder = GestureDescription.Builder()
        val scrollStroke = GestureDescription.StrokeDescription(scrollPath, 0, 500)
        scrollBuilder.addStroke(scrollStroke)
        
        val scrollResult = dispatchGesture(scrollBuilder.build(), object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                Log.d(TAG, "System scroll completed successfully")
                checkScrollResult()
            }
            
            override fun onCancelled(gestureDescription: GestureDescription?) {
                Log.e(TAG, "System scroll cancelled. Possible reasons:")
                Log.e(TAG, "1. The gesture was interrupted by a higher priority gesture")
                Log.e(TAG, "2. The service lost focus or was disabled during the gesture")
                Log.e(TAG, "3. The gesture was too complex or fast for the system to handle")
                Log.e(TAG, "4. There might be an issue with the accessibility permissions")
                Log.e(TAG, "Gesture description: $gestureDescription")
                
                // 尝试获取更多上下文信息
                val root = rootInActiveWindow
                if (root != null) {
                    Log.e(TAG, "Current window class: ${root.className}")
                    Log.e(TAG, "Current window package: ${root.packageName}")
                    root.recycle()
                } else {
                    Log.e(TAG, "Unable to get root window information")
                }
                
                speakOut("Scroll failed")
            }
        }, null)
        
        if (scrollResult) {
            Log.d(TAG, "System scroll initiated successfully")
        } else {
            Log.e(TAG, "Failed to initiate system scroll. Possible reasons:")
            Log.e(TAG, "1. The service might not have the necessary permissions")
            Log.e(TAG, "2. The system might be in a state where it can't accept gestures")
            Log.e(TAG, "3. There might be a problem with the gesture description")
            speakOut("Unable to start scroll")
        }
    }

    // 添加 checkScrollResult 方法
    private fun checkScrollResult() {
        // 这里可以添加检查滚动结果的逻辑
        // 例如，比较滚动前后的内容是否发生变化
        speakOut("Scrolled")
    }

    // 添加新方法来执行最终的滚动操作
    // Updated to use local ScrollDirection, mapping happens in listener override
    private fun performFinalScroll(scrollDirections: Array<ScrollDirection>) {
        Log.d(TAG, "Performing final scroll using local ScrollDirection: ${scrollDirections.joinToString()}")
        
        val beforeScrollWindow = getActiveWindowInfo()
        Log.d(TAG, "Before scroll - $beforeScrollWindow")

        val lastDirection = scrollDirections.lastOrNull() ?: return
        
        val distanceY = when (lastDirection) {
            ScrollDirection.UP -> 100f 
            ScrollDirection.DOWN -> -100f 
            else -> 0f 
        }

        if (distanceY != 0f) {
            val currentTime = System.currentTimeMillis()
            // Use GestureManager's constant for cooldown
            if (currentTime - lastScrollTime > GestureManager.SCROLL_COOLDOWN) { 
                performScroll(0f, distanceY)
                lastScrollTime = currentTime

                // 在滚动操作后稍作延迟，然后获取窗口信息
                Handler(Looper.getMainLooper()).postDelayed({
                    val afterScrollWindow = getActiveWindowInfo()
                    Log.d(TAG, "After scroll - $afterScrollWindow")

                    // 比较滚动前后的窗口信息
                    if (beforeScrollWindow == afterScrollWindow) {
                        Log.d(TAG, "Scroll operation performed in the same window")
                    } else {
                        Log.w(TAG, "Window changed during scroll operation")
                    }
                }, 500) // 500ms 延迟，可以根据需要调整
            }
        }
    }

    // 添加一个新的方法来获取当前活动窗口的信息
    private fun getActiveWindowInfo(): String {
        val root = rootInActiveWindow
        return if (root != null) {
            val info = "Window class: ${root.className}, package: ${root.packageName}"
            root.recycle()
            info
        } else {
            "Unable to get root window information"
        }
    }

    private fun adjustCoordinates(rect: Rect): Rect {
        val statusBarHeight = getStatusBarHeight()
        return Rect(rect.left, rect.top - statusBarHeight, rect.right, rect.bottom - statusBarHeight)
    }

    private fun getStatusBarHeight(): Int {
        val resourceId = resources.getIdentifier("status_bar_height", "dimen", "android")
        return if (resourceId > 0) resources.getDimensionPixelSize(resourceId) else 0
    }

    private fun performClickOnFocusedElement() {
        currentFocusedVirtualNode?.let {
            performClickOnVirtualNode(it)
        } ?: speakOut("无聚焦元素可点击")
    }
    
    // 查找可点击的子节点
    private fun findClickableChild(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            
            if (child.isClickable) {
                return child
            }
            
            // 递归检查子节点的子节点
            val clickableDescendant = findClickableChild(child)
            if (clickableDescendant != null) {
                child.recycle()
                return clickableDescendant
            }
            
            child.recycle()
        }
        return null
    }

    // 修改焦点跟踪方法，使用虚拟节点
    private fun handleFocusTracking(x: Float, y: Float) {
        // 直接用虚拟节点查找
        val nearestVNode = findNearestVirtualNode(x, y)
        if (nearestVNode != null && nearestVNode != currentFocusedVirtualNode) {
            Log.d(TAG, "找到新的可聚焦虚拟节点: ${getVirtualNodeDescription(nearestVNode)}")
            updateFocusAndSpeak(nearestVNode)
        }
    }

    /**
     * 检查事件是否来自系统UI区域（状态栏、导航栏等）
     * @param event AccessibilityEvent事件
     * @return 如果事件来自系统UI区域，返回true；否则返回false
     */
    private fun isSystemUIEvent(event: AccessibilityEvent): Boolean {
        // 检查包名是否为系统UI
        val packageName = event.packageName?.toString()
        if (packageName == "com.android.systemui") {
            return true
        }
        
        // 检查类名是否包含系统UI相关组件
        val className = event.className?.toString()
        if (className != null && (
                className.contains("StatusBar") ||
                className.contains("NavigationBar") ||
                className.contains("SystemUI") ||
                className.contains("QuickSettings") ||
                className.contains("Notification") ||
                className.contains("KeyguardStatus")
            )) {
            return true
        }
        
        // 检查源节点是否在系统UI区域
        val source = event.source
        if (source != null) {
            try {
                val rect = Rect()
                source.getBoundsInScreen(rect)
                
                // 获取状态栏高度
                val statusBarHeight = getStatusBarHeight()
                
                // 如果元素完全位于状态栏区域内
                if (rect.bottom <= statusBarHeight) {
                    return true
                }
                
                // 获取导航栏高度
                val navBarHeight = getNavigationBarHeight()
                val displayMetrics = resources.displayMetrics
                val screenHeight = displayMetrics.heightPixels
                
                // 如果元素完全位于导航栏区域内
                if (rect.top >= screenHeight - navBarHeight) {
                    return true
                }
            } finally {
                source.recycle()
            }
        }
        
        return false
    }

    // 获取下一个节点，修改为倒序遍历子节点
    private fun getNextNodeInHierarchy(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (node == null) return null

        // 检查是否有子节点，按倒序遍历（优先考虑最后添加的子节点）
        if (node.childCount > 0) {
            // 返回最后一个子节点而不是第一个
            return node.getChild(node.childCount - 1)
        }
        
        var currentNode: AccessibilityNodeInfo? = node
        var parentNode: AccessibilityNodeInfo? = currentNode?.parent
        
        while (parentNode != null) {
            val childCount = parentNode.childCount
            
            // 查找当前节点在父节点中的索引
            var currentIndex = -1
            for (i in 0 until childCount) {
                val child = parentNode.getChild(i)
                if (child != null && currentNode != null && child == currentNode) {
                    currentIndex = i
                    child.recycle()
                    break
                }
                child?.recycle()
            }
            
            if (currentIndex > 0) {
                // 如果有上一个兄弟节点，返回它
                return parentNode.getChild(currentIndex - 1)
            }
            
            // 如果没有上一个兄弟节点，移动到父节点
            val nextParent = parentNode.parent
            if (currentNode != null && currentNode != parentNode) {
                currentNode.recycle()
            }
            currentNode = parentNode
            parentNode = nextParent
        }
        
        // 到达层级顶端，返回null
        return null
    }

    // 判断节点是否可访问
    private fun isNodeAccessible(node: AccessibilityNodeInfo): Boolean {
        return node.isFocusable || node.isClickable
    }

    companion object {
        private const val TAG = "ScreenReaderService"
    }

    // 在ScreenReaderService类中添加一个新的辅助方法，用于检查节点是否是ViewGroup
    private fun isViewGroup(node: AccessibilityNodeInfo): Boolean {
        val className = node.className?.toString() ?: ""
        return className == "android.view.ViewGroup" || 
               className.endsWith(".ViewGroup") ||
               className.contains("Layout") // 大多数布局都是ViewGroup的子类
    }

    private fun updateCachedFocusableNodes() {
        val root = rootInActiveWindow ?: return
        val hash = System.identityHashCode(root)
        if (hash != cachedRootHash) {
            Log.d(TAG, "更新节点缓存，新的视图哈希: $hash")
            // 回收旧的缓存节点
            cachedFocusableNodes.forEach { it.recycle() }
            
            // 获取新的节点列表
            val allNodes = getAllNodes(root)
            
            // 先筛选出所有可访问且在屏幕内的节点
            val accessibleNodes = allNodes.filter { isNodeAccessible(it) && isNodeWithinScreen(it) }
            
            // 创建一个集合来存储需要保留的节点
            val nodesToKeep = mutableSetOf<AccessibilityNodeInfo>()
            
            // 遍历所有可访问节点
            for (node in accessibleNodes) {
                // 查找该节点的直接可访问子节点
                val accessibleChildren = accessibleNodes.filter { otherNode -> 
                    node != otherNode && isDirectChildOf(node, otherNode)
                }
                
                // 判断是否要排除该节点：
                // 1. 只有当节点只有一个可访问子节点时才考虑排除
                // 2. 且父子节点边界重叠度较高
                var shouldExclude = false
                if (accessibleChildren.size == 1) {
                    // 获取父节点和子节点的边界
                    val parentRect = Rect()
                    val childRect = Rect()
                    node.getBoundsInScreen(parentRect)
                    accessibleChildren[0].getBoundsInScreen(childRect)
                    
                    // 计算重叠面积与父节点面积的比例
                    val overlapRatio = calculateOverlapRatio(parentRect, childRect)
                    
                    // 如果重叠比例超过70%，认为是同一UI元素的重复，排除父节点
                    shouldExclude = overlapRatio > 0.7
                }
                
                // 如果节点不应被排除，则保留它
                if (!shouldExclude) {
                    nodesToKeep.add(node)
                }
            }
            
            // 将过滤后的节点集合转换为列表
            cachedFocusableNodes = nodesToKeep.toList()
            
            // 更新网格索引
            updateNodePositionMap()
            
            cachedRootHash = hash
        }
    }
    
    // 添加辅助方法，计算两个矩形的重叠比例
    private fun calculateOverlapRatio(rect1: Rect, rect2: Rect): Float {
        // 计算重叠区域
        val overlapRect = Rect()
        if (!overlapRect.setIntersect(rect1, rect2)) {
            return 0f // 没有重叠
        }
        
        // 重叠面积
        val overlapArea = overlapRect.width() * overlapRect.height()
        // 父节点面积
        val parentArea = rect1.width() * rect1.height()
        
        // 返回重叠面积占父节点面积的比例
        return if (parentArea > 0) overlapArea.toFloat() / parentArea else 0f
    }
    
    // 检查一个节点是否是另一个节点的直接父节点
    private fun isDirectChildOf(possibleParent: AccessibilityNodeInfo, possibleChild: AccessibilityNodeInfo): Boolean {
        val parent = possibleChild.parent
        if (parent != null) {
            val isDirectParent = (parent == possibleParent)
            parent.recycle()
            return isDirectParent
        }
        return false
    }
    
    // 添加辅助方法，检查一个节点是否是另一个节点的父节点(任意层级)
    private fun isParentOf(possibleParent: AccessibilityNodeInfo, possibleChild: AccessibilityNodeInfo): Boolean {
        var parent: AccessibilityNodeInfo? = possibleChild.parent
        while (parent != null) {
            if (parent == possibleParent) {
                parent.recycle()
                return true
            }
            val nextParent = parent.parent
            parent.recycle()
            parent = nextParent
        }
        return false
    }

    // 添加确保缓存更新的方法
    private fun ensureCacheUpdated() {
        if (needUpdateCache) {
            updateCachedFocusableNodes()
            updateNodePositionMap()
            needUpdateCache = false
        }
    }

    // 新增基于位置的节点索引方法
    private fun updateNodePositionMap() {
        // 清空旧的映射
        nodePositionMap.values.forEach { nodes ->
            nodes.clear()
        }
        nodePositionMap.clear()
        
        for (node in cachedFocusableNodes) {
            val rect = Rect()
            node.getBoundsInScreen(rect)
            
            val centerX = rect.centerX()
            val centerY = rect.centerY()
            
            // 计算网格单元坐标
            val gridX = centerX / GRID_CELL_SIZE
            val gridY = centerY / GRID_CELL_SIZE
            
            // 存储节点到位置映射（一个位置可以有多个节点）
            val gridKey = Pair(gridX, gridY)
            val nodesList = nodePositionMap.getOrPut(gridKey) { mutableListOf() }
            nodesList.add(node)
        }
    }

    // 从缓存中查找最近的可聚焦节点
    private fun findNearestFocusableNodeFromCache(lastFocusRect: Rect?): AccessibilityNodeInfo? {
        if (lastFocusRect == null) return null
        
        val centerX = lastFocusRect.centerX()
        val centerY = lastFocusRect.centerY()
        
        // 如果缓存为空，确保更新
        if (cachedFocusableNodes.isEmpty()) {
            ensureCacheUpdated()
        }
        
        // 计算中心点所在的网格单元
        val gridX = centerX / GRID_CELL_SIZE
        val gridY = centerY / GRID_CELL_SIZE
        
        // 首先检查当前网格单元中是否有节点
        val exactNodesList = nodePositionMap[Pair(gridX, gridY)]
        if (exactNodesList != null && exactNodesList.isNotEmpty()) {
            // 如果网格单元中有多个节点，找到最近的一个
            if (exactNodesList.size == 1) {
                return exactNodesList[0]
            } else {
                var minDistance = Double.MAX_VALUE
                var nearestNode: AccessibilityNodeInfo? = null
                
                for (node in exactNodesList) {
                    val rect = Rect()
                    node.getBoundsInScreen(rect)
                    val distance = calculateDistance(lastFocusRect, rect)
                    
                    if (distance < minDistance) {
                        minDistance = distance
                        nearestNode = node
                    }
                }
                
                return nearestNode
            }
        }
        
        // 如果当前网格单元没有节点，搜索附近的网格单元
        var minDistance = Double.MAX_VALUE
        var nearestNode: AccessibilityNodeInfo? = null
        
        // 搜索半径为2的网格单元（可根据需要调整）
        for (i in -2..2) {
            for (j in -2..2) {
                // 跳过已检查的当前网格单元
                if (i == 0 && j == 0) continue
                
                val neighborNodes = nodePositionMap[Pair(gridX + i, gridY + j)]
                if (neighborNodes != null && neighborNodes.isNotEmpty()) {
                    for (node in neighborNodes) {
                        val rect = Rect()
                        node.getBoundsInScreen(rect)
                        val distance = calculateDistance(lastFocusRect, rect)
                        
                        if (distance < minDistance) {
                            minDistance = distance
                            nearestNode = node
                        }
                    }
                }
            }
        }
        
        // 如果附近网格单元也没有找到节点，搜索所有缓存的节点
        if (nearestNode == null) {
            for (node in cachedFocusableNodes) {
                val rect = Rect()
                node.getBoundsInScreen(rect)
                val distance = calculateDistance(lastFocusRect, rect)
                
                if (distance < minDistance) {
                    minDistance = distance
                    nearestNode = node
                }
            }
        }
        
        return nearestNode
    }

    // 判断一个矩形是否在屏幕中央
    private fun isCentralOnScreen(rect: Rect): Boolean {
        val centerX = rect.centerX()
        val centerY = rect.centerY()
        
        // 计算屏幕中央区域（中央区域定义为屏幕尺寸的40%）
        val screenCenterX = screenWidth / 2
        val screenCenterY = screenHeight / 2
        val centralRegionWidth = screenWidth * 0.4f
        val centralRegionHeight = screenHeight * 0.4f
        
        return centerX > screenCenterX - centralRegionWidth / 2 &&
               centerX < screenCenterX + centralRegionWidth / 2 &&
               centerY > screenCenterY - centralRegionHeight / 2 &&
               centerY < screenCenterY + centralRegionHeight / 2
    }

    // 判断视图是否包含可交互元素
    private fun hasInteractiveElements(node: AccessibilityNodeInfo): Boolean {
        if (isNodeAccessible(node)) return true
        
        if (isViewGroup(node)) {
            // 对于ViewGroup，倒序遍历子节点
            for (i in node.childCount - 1 downTo 0) {
                val child = node.getChild(i) ?: continue
                if (hasInteractiveElements(child)) {
                    child.recycle()
                    return true
                }
                child.recycle()
            }
        } else {
            // 对于非ViewGroup，正序遍历子节点
            for (i in 0 until node.childCount) {
                val child = node.getChild(i) ?: continue
                if (hasInteractiveElements(child)) {
                    child.recycle()
                    return true
                }
                child.recycle()
            }
        }
        
        return false
    }

    // 判断一个节点是否在指定视图层级内
    private fun isNodeInHierarchy(node: AccessibilityNodeInfo?, hierarchyRoot: AccessibilityNodeInfo?): Boolean {
        if (node == null || hierarchyRoot == null) return false
        
        // 如果节点就是层级根节点
        if (node == hierarchyRoot) return true
        
        // 获取节点的所有父节点
        var parent = node.parent
        while (parent != null) {
            if (parent == hierarchyRoot) {
                parent.recycle()
                return true
            }
            val nextParent = parent.parent
            parent.recycle()
            parent = nextParent
        }
        
        return false
    }

    private fun findFirstAccessibleNode(root: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (root == null) return null
        
        if (isNodeAccessible(root)) return root
        
        if (isViewGroup(root)) {
            // 对于ViewGroup，倒序遍历子节点
            for (i in root.childCount - 1 downTo 0) {
                val child = root.getChild(i) ?: continue
                val accessible = findFirstAccessibleNode(child)
                if (accessible != null) {
                    child.recycle()
                    return accessible
                }
                child.recycle()
            }
        } else {
            // 对于非ViewGroup，正序遍历子节点
            for (i in 0 until root.childCount) {
                val child = root.getChild(i) ?: continue
                val accessible = findFirstAccessibleNode(child)
                if (accessible != null) {
                    child.recycle()
                    return accessible
                }
                child.recycle()
            }
        }
        
        return null
    }


    private fun notifyPCUiUpdated() {
        val now = System.currentTimeMillis()
        // 2秒内不重复发送
        if (now - lastUiUpdateTime < 2000) {
            Log.d(TAG, "UI_UPDATED skipped due to debounce.")
            return
        }
        lastUiUpdateTime = now
        val timestamp = java.text.SimpleDateFormat("MMddHHmmss", java.util.Locale.getDefault()).format(java.util.Date())
        sendPCSignal("UI_UPDATED", mapOf("timestamp" to timestamp))
    }

    /**
     * 通用PC信号发送方法，通过socket向PC端发送JSON信号。
     * @param type 信号类型，如"ROLE"、"UI_UPDATED"等
     * @param data 额外的键值对，将作为顶层字段加入JSON
     */
    private fun sendPCSignal(type: String, data: Map<String, String>) {
        Thread {
            try {
                val json = JSONObject()
                json.put("type", type)
                for ((k, v) in data) {
                    json.put(k, v)
                }
                val jsonString = json.toString()
                val socket = java.net.Socket("127.0.0.1", 9998)
                val writer = java.io.PrintWriter(socket.getOutputStream(), true)
                writer.println(jsonString)
                Thread.sleep(100) // 确保数据发送完成
                writer.close()
                socket.close()
                Log.d(TAG, "PC信号已发送: $jsonString")
            } catch (e: Exception) {
                Log.e(TAG, "发送PC信号失败: ${e.message}")
            }
        }.start()
    }

    // 生成唯一hash id的方法，使用viewIdResourceName+类名+left+top+right+bottom
    private fun generateElementHashId(viewIdResourceName: CharSequence?, className: CharSequence?, rect: Rect): String {
        val viewId = viewIdResourceName?.toString() ?: "null"
        val classStr = className?.toString() ?: "null"
        val raw = viewId + "_" + classStr + "_" + rect.left + "_" + rect.top + "_" + rect.right + "_" + rect.bottom
        val hash = raw.hashCode().toUInt().toString(16)
        return "element_${hash}"
    }

    // ========== 虚拟树聚焦索引与状态管理 ========== 
    // private var currentVirtualFocusIndex: Int = -1 // 当前聚焦虚拟节点索引
    // private var currentFocusedVirtualNode: VirtualNode? = null // 当前聚焦虚拟节点

    // ========== 虚拟树聚焦切换与导航 ========== 
    // 切换到下一个虚拟节点
    private fun moveVirtualFocusToNext() {
        if (focusableVirtualNodes.isEmpty()) {
            speakOut("没有可聚焦元素")
            return
        }
        val nextIndex = if (currentVirtualFocusIndex < focusableVirtualNodes.size - 1) currentVirtualFocusIndex + 1 else 0
        setVirtualFocus(nextIndex)
    }
    // 切换到上一个虚拟节点
    private fun moveVirtualFocusToPrevious() {
        if (focusableVirtualNodes.isEmpty()) {
            speakOut("没有可聚焦元素")
            return
        }
        val prevIndex = if (currentVirtualFocusIndex > 0) currentVirtualFocusIndex - 1 else focusableVirtualNodes.size - 1
        setVirtualFocus(prevIndex)
    }
    // 设置虚拟聚焦
    private fun setVirtualFocus(index: Int) {
        if (index < 0 || index >= focusableVirtualNodes.size) return
        currentVirtualFocusIndex = index
        val node = focusableVirtualNodes[index]
        currentFocusedVirtualNode = node
        updateFocusAndSpeak(node)
    }

    // ========== Overlay 高亮与朗读方法统一 ========== 
    // 用虚拟节点高亮并朗读
    private fun updateFocusAndSpeak(node: VirtualNode) {
        // 更新当前聚焦的虚拟节点引用
        currentFocusedVirtualNode = node
        
        // 焦点移动时震动反馈
        try {
            if (::vibrator.isInitialized && vibrator.hasVibrator()) {
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                    vibrator.vibrate(VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE))
                } else {
                    @Suppress("DEPRECATION")
                    vibrator.vibrate(50)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Vibrator error: ${e.message}")
        }
        
        // 日志输出虚拟节点聚焦信息
        Log.d(TAG, "虚拟聚焦: id=${node.id}, text=${node.text}, contentDescription=${node.contentDescription}")
        
        // 获取状态栏高度
        val statusBarHeight = getStatusBarHeight()
        
        // 调整矩形坐标
        val adjustedRect = adjustCoordinates(node.bounds)
        
        // 获取屏幕尺寸
        val displayMetrics = resources.displayMetrics
        val screenWidth = displayMetrics.widthPixels
        val screenHeight = displayMetrics.heightPixels
        
        // 检查调整后的矩形是否在屏幕范围内
        if (adjustedRect.isEmpty || !Rect(0, 0, screenWidth, screenHeight).contains(adjustedRect)) {
            // 可以在这里添加额外的处理逻辑，比如使用默认大小的矩形
        }
        
        // 记录焦点覆盖层的实际尺寸
        focusOverlayView.post {
            // Log.d(TAG, "FocusOverlay actual size: ${focusOverlayView.width}x${focusOverlayView.height}")
        }
        
        // 更新焦点矩形
        focusOverlayView.updateFocusRect(adjustedRect)
        
        // speak out 之前，再次确认最终的位置
        focusOverlayView.post {
            val finalRect = focusOverlayView.getFocusRect()
            if (finalRect != adjustedRect) {
                // Log.w(TAG, "Focus rect mismatch: expected $adjustedRect, but drew $finalRect")
            }
        }
        
        // 朗读节点描述 - 使用新的描述获取方法
        val desc = getVirtualNodeDescription(node)
        speakOut(desc)
        
        // 记录交互日志（如果需要对虚拟节点也记录日志的话）
        node.realNode?.let { 
            // 同时更新currentFocusedNode，保持引用一致性
            currentFocusedNode = it
            logUIInteraction(it) 
        }
    }

    // ========== 虚拟节点点击与真实交互 ========== 
    private fun performClickOnVirtualNode(node: VirtualNode) {
        // 新增：递归查找最近的可点击父节点
        fun findClickableAncestor(n: VirtualNode?): VirtualNode? {
            var current = n
            while (current != null) {
                if (current.isClickable) return current
                current = current.parent
            }
            return null
        }
        val clickableNode = findClickableAncestor(node)
        if (clickableNode == null) {
            speakOut("无可点击元素")
            return
        }
        when (clickableNode.type) {
            VirtualNode.NodeType.REAL -> {
                clickableNode.realNode?.let { real ->
                    val rect = clickableNode.bounds
                    val centerX = (rect.left + rect.right) / 2f
                    val centerY = (rect.top + rect.bottom) / 2f
                    // 优先用 performAction
                    val clicked = real.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    if (!clicked) {
                        // 退化为 dispatchGesture
                        performClick(centerX, centerY)
                    } else {
                        speakOut("已点击")
                    }
                } ?: speakOut("无可点击元素")
            }
            VirtualNode.NodeType.STATIC_TEXT -> {
                speakOut("此为静态文本，无操作")
            }
        }
    }

    // ========== Overlay 导航事件拦截重构 ========== 
    // 修改 overlayView 的 onTouchListener，拦截手势只切换虚拟节点

    // ========== 虚拟树辅助方法 ========== 
    // 按坐标查找最近虚拟节点
    private fun findNearestVirtualNode(x: Float, y: Float): VirtualNode? {
        if (focusableVirtualNodes.isEmpty()) return null
        var minDist = Double.MAX_VALUE
        var nearest: VirtualNode? = null
        for (node in focusableVirtualNodes) {
            val c = node.center
            val dist = Math.hypot((c.first - x).toDouble(), (c.second - y).toDouble())
            if (dist < minDist) {
                minDist = dist
                nearest = node
            }
        }
        return nearest
    }

    // 新增方法：处理真实节点聚焦，转换为虚拟节点
    private fun handleRealNodeFocus(realNode: AccessibilityNodeInfo) {
        // 尝试在现有虚拟树中查找对应的虚拟节点
        val virtualNode = findVirtualNodeForRealNode(realNode)
        
        if (virtualNode != null) {
            // 找到对应的虚拟节点，使用虚拟节点版本的方法
            updateFocusAndSpeak(virtualNode)
        } else {
            // 如果没有找到对应的虚拟节点，创建一个临时的虚拟节点
            val rect = Rect()
            realNode.getBoundsInScreen(rect)
            val centerX = (rect.left + rect.right) / 2
            val centerY = (rect.top + rect.bottom) / 2
            
            val tempVirtualNode = VirtualNode(
                id = realNode.viewIdResourceName ?: "${realNode.className}_${centerX}_${centerY}",
                type = VirtualNode.NodeType.REAL,
                canFocus = true,
                text = realNode.text,
                contentDescription = realNode.contentDescription,
                viewIdResourceName = realNode.viewIdResourceName,
                className = realNode.className,
                isClickable = realNode.isClickable,
                isCheckable = realNode.isCheckable,
                isChecked = realNode.isChecked,
                isFocusable = realNode.isFocusable,
                isEnabled = realNode.isEnabled,
                isPassword = realNode.isPassword,
                isSelected = realNode.isSelected,
                bounds = Rect(rect),
                center = Pair(centerX, centerY),
                realNode = realNode,
                children = mutableListOf(),
                parent = null
            )
            
            // 使用临时虚拟节点
            updateFocusAndSpeak(tempVirtualNode)
        }
    }
    
    // 在虚拟树中查找对应的真实节点
    private fun findVirtualNodeForRealNode(realNode: AccessibilityNodeInfo): VirtualNode? {
        if (virtualRoot == null || focusableVirtualNodes.isEmpty()) {
            // 如果虚拟树为空，构建虚拟树
            buildVirtualTree()
        }
        
        // 在可聚焦的虚拟节点中查找
        for (vNode in focusableVirtualNodes) {
            // 检查是否是同一个真实节点
            if (vNode.realNode != null && vNode.realNode == realNode) {
                return vNode
            }
            
            // 同时检查位置和内容是否匹配，增加匹配成功的可能性
            val rect = Rect()
            realNode.getBoundsInScreen(rect)
            if (vNode.bounds == rect && 
                vNode.text == realNode.text && 
                vNode.contentDescription == realNode.contentDescription &&
                vNode.className == realNode.className) {
                return vNode
            }
        }
        
        return null
    }

    // ========== 虚拟节点描述处理方法 ========== 
    private fun getVirtualNodeDescription(node: VirtualNode): String {
        // 首先检查节点自身是否有文本或描述
        val text = node.text
        if (!text.isNullOrBlank()) {
            return text.toString()
        }

        val contentDescription = node.contentDescription
        if (!contentDescription.isNullOrBlank()) {
            return contentDescription.toString()
        }

        // 如果当前节点没有描述，收集所有不可聚焦子节点的内容
        return collectAllVirtualChildrenDescriptions(node)
    }
    
    // 新增方法：收集所有不可聚焦虚拟子节点的描述
    private fun collectAllVirtualChildrenDescriptions(node: VirtualNode): String {
        val descriptions = mutableListOf<String>()
        collectVirtualDescriptionsRecursively(node, descriptions, HashSet())
        
        return if (descriptions.isEmpty()) {
            node.className?.toString() ?: "未命名元素"
        } else {
            descriptions.joinToString(", ")
        }
    }
    
    // 递归收集所有虚拟子节点的描述
    private fun collectVirtualDescriptionsRecursively(node: VirtualNode, descriptions: MutableList<String>, visitedNodes: HashSet<String>) {
        // 防止循环引用导致的无限递归
        if (visitedNodes.contains(node.id)) {
            return
        }
        visitedNodes.add(node.id)
        
        // 遍历所有子节点
        for (child in node.children) {
            // 如果子节点可以聚焦，则跳过（因为这些节点会单独被朗读）
            if (child.canFocus) {
                continue
            }
            
            // 获取子节点的描述
            val childText = child.text?.toString()
            val childContentDesc = child.contentDescription?.toString()
            
            // 如果子节点有描述，则添加到列表中
            if (!childText.isNullOrBlank()) {
                descriptions.add(childText)
            } else if (!childContentDesc.isNullOrBlank()) {
                descriptions.add(childContentDesc)
            } else {
                // 如果子节点没有描述，则递归检查其子节点
                collectVirtualDescriptionsRecursively(child, descriptions, visitedNodes)
            }
        }
    }

    // 判断节点是否在屏幕内
    private fun isNodeWithinScreen(node: AccessibilityNodeInfo): Boolean {
        val rect = Rect()
        node.getBoundsInScreen(rect)
        // 获取状态栏高度
        val statusBarHeight = getStatusBarHeight()
        // 调整坐标以考虑状态栏
        val adjustedRect = adjustCoordinates(rect)
        // 简化边界检查
        val isWithinBounds = adjustedRect.left >= 0 &&
                              adjustedRect.right <= screenWidth &&
                              adjustedRect.top >= 0 &&
                              adjustedRect.bottom < screenHeight
        return isWithinBounds
    }

    // --- GestureListener Implementation ---
    override fun onSingleTapConfirmed(event: MotionEvent) {
        Log.d(TAG, "GestureListener: Single tap confirmed at (${event.x}, ${event.y})")
        // Original ScreenReaderService onSingleTapConfirmed was empty.
    }

    override fun onDoubleTap(event: MotionEvent) {
        Log.d(TAG, "GestureListener: Double tap reported by GestureManager.")
        performClickOnFocusedElement()
        this.isDoubleClickAction = true // Update service state
        // gestureManager.isDoubleClickAction is set true inside GestureManager

        handler.postDelayed({
            Log.d(TAG, "Post-double-tap: Capturing UI.")
            captureAndSaveUIElements()
            notifyPCUiUpdated()
            this.isDoubleClickAction = false // Reset in service
            gestureManager.isDoubleClickAction = false // Reset in manager
        }, 2000)
    }

    override fun onScroll(e1: MotionEvent?, e2: MotionEvent, distanceX: Float, distanceY: Float): Boolean {
        Log.d(TAG, "GestureListener: Scroll reported by GestureManager. isScrolling in manager: ${gestureManager.isScrolling}")
        // ScreenReaderService's isScrolling and scrollPath are now managed by GestureManager.
        // This callback is for any additional service-level reaction to an ongoing scroll.
        return true
    }

    override fun onFling(e1: MotionEvent?, e2: MotionEvent, velocityX: Float, velocityY: Float): Boolean {
        Log.d(TAG, "GestureListener: Generic Fling reported by GestureManager (velX: $velocityX, velY: $velocityY)")
        // Specific fling actions (left/right) are handled by onFlingRight/Left.
        // This can be used for other fling-related logic if necessary.
        return true
    }

    override fun onFlingRight() {
        Log.d(TAG, "GestureListener: Fling Right reported by GestureManager.")
        moveVirtualFocusToNext()
    }

    override fun onFlingLeft() {
        Log.d(TAG, "GestureListener: Fling Left reported by GestureManager.")
        moveVirtualFocusToPrevious()
    }

    override fun onLongPressStateChanged(isPressing: Boolean, x: Float, y: Float) {
        Log.d(TAG, "GestureListener: Long press state changed to $isPressing at ($x, $y), reported by GestureManager.")
        this.isLongPressing = isPressing
        if (isPressing) {
            // Original logic started focus tracking as soon as long press was detected.
            handleFocusTracking(x, y)
        }
    }

    override fun onFocusTracking(x: Float, y: Float) {
        Log.d(TAG, "GestureListener: Focus tracking at ($x, $y) reported by GestureManager.")
        // This is called when long press is active and finger is moving.
        handleFocusTracking(x, y)
    }

    override fun onPerformFinalScroll(gmScrollDirections: Array<GestureManager.ScrollDirection>) {
        Log.d(TAG, "GestureListener: Perform final scroll (from two-finger scroll) reported by GestureManager. Directions: ${gmScrollDirections.joinToString()}")
        val localScrollDirections = gmScrollDirections.mapNotNull { gmDir ->
            try {
                ScrollDirection.valueOf(gmDir.name) // Map from GestureManager.ScrollDirection to local ScreenReaderService.ScrollDirection
            } catch (e: IllegalArgumentException) {
                Log.w(TAG, "Cannot map GestureManager.ScrollDirection.${gmDir.name} to local ScrollDirection.")
                null
            }
        }.toTypedArray()

        if (localScrollDirections.isNotEmpty() || gmScrollDirections.isEmpty()) {
            performFinalScroll(localScrollDirections)
        } else if (gmScrollDirections.isNotEmpty()){
             Log.w(TAG, "Scroll direction array became empty after mapping and was not originally empty. Original GM Dirs: ${gmScrollDirections.joinToString()}")
        }
    }
}

private fun eventTypeToString(eventType: Int): String {
    return when (eventType) {
        AccessibilityEvent.TYPE_VIEW_FOCUSED -> "VIEW_FOCUSED"
        AccessibilityEvent.TYPE_VIEW_CLICKED -> "VIEW_CLICKED"
        AccessibilityEvent.TYPE_VIEW_SELECTED -> "VIEW_SELECTED"
        AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> "WINDOW_STATE_CHANGED"
        AccessibilityEvent.TYPE_VIEW_SCROLLED -> "VIEW_SCROLLED"
        AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> "WINDOW_CONTENT_CHANGED"
        else -> "UNKNOWN"
    }
}

private fun getEventDescription(event: AccessibilityEvent): String {
    val eventText = event.text.joinToString(" ")
    return when (event.eventType) {
        AccessibilityEvent.TYPE_VIEW_FOCUSED -> "Focused: $eventText"
        AccessibilityEvent.TYPE_VIEW_CLICKED -> "Clicked: $eventText"
        AccessibilityEvent.TYPE_VIEW_SELECTED -> "Selected: $eventText"
        AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> "Window changed: $eventText"
        AccessibilityEvent.TYPE_VIEW_SCROLLED -> "Scrolled: $eventText"
        AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> {
            // Only announce significant content changes
            if (isSignificantChange(event)) {
                "Content changed: $eventText"
            } else {
                "null"
            }
        }
        else -> eventText
    }
}

private fun isSignificantChange(event: AccessibilityEvent): Boolean {
    // Check if the event text is empty, only whitespace, or only symbols
    val eventText = event.text.joinToString(" ").trim()
    if (eventText.isEmpty() || eventText.matches(Regex("^[\\s\\p{Punct}]+$"))) {
        return false
    }
    
    // Check if the change type includes text changes
    return event.contentChangeTypes and AccessibilityEvent.CONTENT_CHANGE_TYPE_TEXT != 0
}

// Add this utility class for ISO8601 date formatting
object ISO8601Utils {
    private val format = SimpleDateFormat("MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }

    fun format(date: Date): String = format.format(date)
}
