# FocalFlow

FocalFlow 是辅助盲人和低视力用户完成多步手机任务的研究原型。Android 端基于
Google TalkBack 捕获无障碍树；Python 端结合任务、树和截图选出相关区域；手机
通过焦点标志过滤浏览范围。用户仍在手机上探索和激活控件。

[English README](README.md) · [安装与配置](docs/setup.md) ·
[架构](docs/architecture.md) · [协议](docs/protocol-v1.md) ·
[已知问题](docs/known-issues.md)

当前是 IMWUT26 开源准备用的**私有整合候选**，版权和项目许可证尚待确认。
商家激活停滞、端口重启和 EOF 后捕获竞态仍保留；没有宣称完整点餐流程或论文
实验复现。基线采用成对离线验证快照，与最后一次 Luna 实机运行的启动代码字节
不同；详见[来源说明](docs/source-baseline.md)。

目录分为 `backend/`、`android/`、`docs/` 和 `scripts/`。完整 Android Gradle
模块、资源和上游许可保留，应用 ID 仍为 `com.android.talkback`。

Python 3.8.19/macOS 是参考环境；新建 venv 的依赖安装与离线检查已通过，
不代表全新系统或实机验证。仓库根目录：

```sh
python3.8 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-offline.txt
export FOCALFLOW_PYTHON="$(pwd)/.venv/bin/python"
./scripts/offline-demo.sh
./scripts/check-offline.sh
```

演示使用虚构树、白色小图和固定模型响应，输出 `external_calls=0`。测试不访问
真实手机、凭据、模型接口、音频硬件或下载权重。完整 Java/跨语言检查还需设置
`FF_JAVA_HOME`、`FF_JSON_JAR` 和 `FF_ANDROID_JAR`，见英文 README。

实机手动入口仅支持 macOS：准备模式 600 的仓库外私有配置，通过
`FOCALFLOW_CONFIG` 指定；ADB 使用 `FOCALFLOW_ADB` 或 PATH 查找，继承操作者
代理设置。**先开启手机 FocalFlow，再执行 `./scripts/run-manual.sh`**。收到严格
匹配的 `SESSION_READY` 后才开始捕获；初始等待期间过滤不生效。手动入口保持
点汉堡预设和 24 次聊天 / 12 次 TTS / 600 秒限制；直接运行 `backend/run.py`
仍保留原挂号预设。Ctrl+C 停止后检查手机无障碍服务状态。

菜单中的「恢复标准浏览（暂停 AI）」保留普通浏览；「启用 AI 过滤」重新连接。
无 USB 且仍等待时，可在系统无障碍设置中关闭 FocalFlow。私有日志默认位于
`~/Library/Application Support/FocalFlow/manual-tests`，不要上传真实屏幕、语音
或配置。离线测试通过、ACK 发出或结果送达不等于用户任务完成。

[构建说明](docs/setup.md#android-build)使用完整 Android SDK/NDK；phone debug APK
输出到 `android/build/outputs/apk/phone/debug/`。
源码包不含实际用户/研究数据、权重、APK、签名材料和旧 Git 历史。
[许可状态](docs/licensing-status.md)尚未确定；不要从 Android 上游许可证推断
整个项目或 Python 端的再分发许可。
