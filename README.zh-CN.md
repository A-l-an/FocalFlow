# FocalFlow

FocalFlow 是辅助盲人和低视力用户浏览手机界面的研究原型。Android 端基于 TalkBack 获取当前界面，Python 后端根据用户任务选出相关信息，再让手机只保留对应的焦点。用户自己浏览、点击，也可以通过语音逐步要求显示更多信息。

[English](README.md)

## 1. 项目结构

```text
FocalFlow/
├── android/                  基于 TalkBack 的 Android 应用
│   ├── talkback/             无障碍服务、手势和菜单
│   ├── utils/                界面树、节点映射、焦点过滤和电脑连接
│   └── braille/              上游 TalkBack 的盲文支持
├── backend/
│   ├── run.py                任务规划、界面分类和语音对话流程
│   ├── MobileAgent/          提示词、任务预设、模型与语音接口、结果校验
│   ├── tools/manual_testing/ 日常模式和测试模式共用的启动器
│   ├── examples/             使用虚构界面的离线示例
│   └── tests/                自动化测试
├── scripts/                  Demo 启动和检查命令
└── docs/                     架构、详细配置和通信协议
```

手机和电脑通过 **USB/ADB 与本地 TCP 连接**协作。AI 语音播报和语音识别在电脑上运行；普通 TalkBack 朗读在手机上运行。

## 2. 可以复用的组件

| 你想实现什么 | 从哪里开始看 |
| --- | --- |
| 把 Android 无障碍节点转成 JSON 树，并保留与原生控件的对应关系 | [VirtualTreeBuilder.java][tree-builder]、[NodeMappingManager.java][node-mapping] |
| 让读屏器只访问选定的界面区域 | [FocusProxy.java][focus-proxy]、[VirtualTreeManager.java][tree-manager] |
| 在手机与电脑之间传递分析结果，防止旧页面结果覆盖新页面 | [PcConnectionManager.java][pc-connection]、[protocol.py](backend/MobileAgent/protocol.py)、[validation.py](backend/MobileAgent/validation.py) |
| 将任务规划和界面分类流程改用于其他任务 | [MobileAgentStateMachine](backend/run.py)、[task_presets.py](backend/MobileAgent/task_presets.py)、[prompt.py](backend/MobileAgent/prompt.py) |
| 根据语音要求，把新信息类别加入现有焦点集合 | [run.py](backend/run.py) 的 Talk 阶段、[api.py](backend/MobileAgent/api.py) 的语音接口 |

Android 部分与 TalkBack 集成，复用时需要一起处理界面树和节点映射依赖。后端返回完整界面树，通过 `isVirtualFocusNode` 标记可访问节点；替换后端时可参考[通信协议](docs/protocol-v1.md)。

## 3. 启动并使用 Demo

当前启动器面向 **macOS**，参考 Python 版本为 **3.8.19**。还需要一台支持无障碍多指手势、已开启 USB 调试的 Android 测试手机，以及加入 `PATH` 的 Android platform-tools（`adb`）和 FFmpeg。

### 第一步：准备 Python 后端

以下命令在同一个终端执行：

```sh
git clone https://github.com/A-l-an/FocalFlow.git
cd FocalFlow
python3.8 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-offline.txt
python -m pip install numpy==1.24.4 sounddevice==0.5.1 soundfile==0.13.1 scipy==1.10.0 torch==2.4.1 openai-whisper==20240930
export FOCALFLOW_PYTHON="$(pwd)/.venv/bin/python"
python -c 'import whisper; whisper.load_model("base")'
```

最后一条命令会提前下载本地语音识别模型，避免第一次语音交互时等待下载。macOS 可用 `brew install ffmpeg` 安装 FFmpeg。系统询问麦克风权限时，允许运行后端的终端访问麦克风。

### 第二步：构建并安装 Android 应用

准备 **JDK 16、Android SDK 34、NDK 25.2.9519653**，在 `android/local.properties` 中填写 SDK 路径（`sdk.dir=/path/to/Android/sdk`）。通过 USB 连接手机，并在手机上允许调试，然后执行：

```sh
adb devices
export JAVA_HOME="$(/usr/libexec/java_home -v 16)"
cd android
./gradlew --no-daemon --console=plain :assemblePhoneDebug
cd ..
adb install -r android/build/outputs/apk/phone/debug/*.apk
```

建议使用测试手机：应用包名是 `com.android.talkback`，可能与设备上已有的不同签名应用冲突。更多构建细节见[配置说明](docs/setup.md#android-build)。

### 第三步：配置模型服务

```sh
mkdir -p "$HOME/.config/focalflow"
cp -n backend/tools/manual_testing/providers.env.example "$HOME/.config/focalflow/providers.env"
chmod 600 "$HOME/.config/focalflow/providers.env"
export FOCALFLOW_CONFIG="$HOME/.config/focalflow/providers.env"
```

编辑这个文件，将 `FOCALFLOW_CHAT_API_TOKEN` 和 `OPENAI_API_KEY` 换成自己的密钥。示例使用 `gpt-6-luna` 分析界面，使用 `gpt-4o-mini-tts` 合成语音；聊天模型需要支持图片和文字输入。

截图、界面文字和对话文本会发送给配置的聊天或 TTS 服务，API 调用可能产生费用。配置文件和运行日志请保留在本地。

### 第四步：启动

1. 保持 **一台手机**通过 USB 连接，在手机系统的无障碍设置中开启 **FocalFlow**。
2. 在仓库根目录启动电脑端：

   ```sh
   ./scripts/run.sh
   ```

3. 终端显示后端会话就绪后，在手机上打开美团外卖。默认任务是 **“我要点一份汉堡外卖”**。等待页面说明和分析完成，再浏览过滤后的控件。

启动器会配置 ADB 转发。日常模式持续运行，直到你主动停止。退出时在电脑上按 **Ctrl+C**，再确认手机无障碍设置中的 FocalFlow 已关闭。如果只想跑十分钟测试，改用 `./scripts/run-manual.sh`。

### 第五步：浏览并逐步显示更多信息

| 手机手势 | 用途 |
| --- | --- |
| 单指左右滑动 | 切换可访问焦点 |
| 单指双击 | 激活当前控件 |
| 双指上下滑动 | 滚动页面；页面变化可能触发重新分析 |
| **双指三击并按住**（第三次不抬起） | 请求当前页面的更多信息 |

使用语音时，先等页面分析完成，再做最后一个手势。**电脑**会播报可补充的信息类别；听到录音提示音后，对着**电脑麦克风**说话，例如“再看看价格”。录音在 **五秒后自动结束**。Talk 阶段可以保留现有焦点，再加入所需类别的节点；需要另一类信息时，再进行一轮语音交互。

TalkBack 菜单中还有 **Use standard browsing (pause AI)**（暂停 AI，恢复标准浏览）和 **Enable AI filtering**（启用 AI 过滤）。如果没有响应，先检查手机上的 FocalFlow 是否确实开启，再查看终端错误；仅电脑显示已连接，不能确认手机过滤已生效。

这是研究原型，完整真机任务流程和多轮语音渐进披露仍待验证。

**暂时没有手机？** 安装 `requirements-offline.txt` 后，可运行 `./scripts/offline-demo.sh` 查看处理流程。它使用虚构界面和固定响应，不调用 API。`./scripts/check-offline.sh` 用于运行自动化检查。

---

[架构说明](docs/architecture.md) · [详细配置](docs/setup.md) · [通信协议](docs/protocol-v1.md)

FocalFlow 源码和文档采用 [Apache-2.0](LICENSE)；附带组件的许可见[第三方许可说明](LICENSES/README.md)。

[tree-builder]: android/utils/src/main/java/com/google/android/accessibility/utils/VirtualTreeBuilder.java
[node-mapping]: android/utils/src/main/java/com/google/android/accessibility/utils/NodeMappingManager.java
[focus-proxy]: android/utils/src/main/java/com/google/android/accessibility/utils/FocusProxy.java
[tree-manager]: android/utils/src/main/java/com/google/android/accessibility/utils/VirtualTreeManager.java
[pc-connection]: android/utils/src/main/java/com/google/android/accessibility/utils/PcConnectionManager.java
