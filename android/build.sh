#!/bin/bash

### 用于构建 Talkback-for-Partners Android APK 的 Bash 脚本
###
### 需要预先设置的环境变量：
###   ANDROID_SDK           # 本地 Android SDK 的路径
###   JAVA_HOME             # 本地 Java SDK 的路径

### 示例环境变量配置（供参考）：
# ANDROID_SDK=~/Android/Sdk
# ANDROID_NDK=~/Android/Sdk/ndk
# JAVA_HOME=/usr/local/buildtools/java/jdk
# JAVA_HOME=/google/data/ro/projects/java-platform/linux-amd64/jdk-17-latest/bin

# Gradle 和插件版本帮助文档：
# https://developer.android.com/build/releases/gradle-plugin#updating-gradle
# https://docs.gradle.org/current/userguide/compatibility.html

# 指定要下载的 Gradle 版本
GRADLE_DOWNLOAD_VERSION=7.6.4

# 是否启用 Gradle 构建过程的详细日志
GRADLE_TRACE=false

# 日志函数，用于打印信息
function log {
  if [[ -n $1 ]]; then
    echo "##### ${1}"
  else echo
  fi
}

# 打印错误并退出脚本的函数
function fail_with_message  {
  echo
  echo "Error: ${1}"
  exit 1
}

# 检查环境变量是否设置，如果未设置则退出
function require_environment_variable() {
  if [[ -z ${!1+set} ]]; then
    fail_with_message "the environment variable $1 is not set"
  else
    log "${1}: ${!1}"
  fi
}

# 检查文件夹是否存在，如果不存在则退出
function require_folder_exists() {
  if [[ ! -d "${1}" ]]; then
    fail_with_message "the folder at ${1} does not exist"
  else
    log "ls ${1}"; ls "${1}"
  fi
}

# 输出当前路径和当前目录下的文件
log "pwd: $(pwd)"
log "ls"; ls
log

# 检查并显示 ANDROID_SDK 和 JAVA_HOME 设置情况
require_environment_variable ANDROID_SDK
require_folder_exists "${ANDROID_SDK}"
require_environment_variable JAVA_HOME
require_folder_exists "${JAVA_HOME}"
log

# 写入 Android 项目的 local.properties 文件，用于指定 SDK 路径
log "Write local.properties file"
echo "sdk.dir=${ANDROID_SDK}" > local.properties
log "cat local.properties"; cat local.properties
log

# 构造 Gradle zip 文件名与下载路径
GRADLE_ZIP_REMOTE_FILE=gradle-${GRADLE_DOWNLOAD_VERSION}-bin.zip
GRADLE_ZIP_DEST_PATH=~/${GRADLE_DOWNLOAD_VERSION}.zip

# 使用 wget 下载指定版本的 Gradle 二进制压缩包
log "Download gradle binary from the web ${GRADLE_ZIP_REMOTE_FILE} to ${GRADLE_ZIP_DEST_PATH} using wget"
time wget -O ${GRADLE_ZIP_DEST_PATH} https://services.gradle.org/distributions/${GRADLE_ZIP_REMOTE_FILE}
log

# 解压下载的 Gradle zip 到 /opt 目录下
GRADLE_UNZIP_HOSTING_FOLDER=/opt/gradle-${GRADLE_DOWNLOAD_VERSION}
log "Unzip gradle zipfile ${GRADLE_ZIP_DEST_PATH} to ${GRADLE_UNZIP_HOSTING_FOLDER}"
sudo unzip -n -d ${GRADLE_UNZIP_HOSTING_FOLDER} ${GRADLE_ZIP_DEST_PATH}

# 设置 gradle 可执行文件的路径
GRADLE_BINARY=${GRADLE_UNZIP_HOSTING_FOLDER}/gradle-${GRADLE_DOWNLOAD_VERSION}/bin/gradle
log "\${GRADLE_BINARY} = ${GRADLE_BINARY}"

# 显示 Gradle 版本确认其有效
log "\${GRADLE_BINARY} -version"
${GRADLE_BINARY} -version
log

# 如果开启了调试模式，输出 Gradle 依赖树
if [[ "$GRADLE_TRACE" = true ]]; then
  log "${GRADLE_BINARY} dependencies"
  ${GRADLE_BINARY} dependencies
  log
fi

# 根据是否开启调试设置构建参数
GRADLE_DEBUG=
GRADLE_STACKTRACE=
if [[ "$GRADLE_TRACE" = true ]]; then
  GRADLE_DEBUG=--debug
  GRADLE_STACKTRACE=--stacktrace
fi

# 使用 Gradle 构建 debug 版本 APK
log "${GRADLE_BINARY} assembleDebug"
${GRADLE_BINARY} ${GRADLE_DEBUG} ${GRADLE_STACKTRACE} assembleDebug
BUILD_EXIT_CODE=$?
log

# 如果构建成功，查找生成的 APK 文件
if [[ $BUILD_EXIT_CODE -eq 0 ]]; then
  log "find . -name *.apk"
  find . -name "*.apk"
  log
fi

# 返回构建命令的退出码（成功或失败）
exit $BUILD_EXIT_CODE   ### This should be the last line in this file
