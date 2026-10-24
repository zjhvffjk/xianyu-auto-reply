#!/bin/sh
# WebSocket 服务容器启动脚本
#
# 作用：先拉起 Xvfb 虚拟显示，再启动主程序。
# 背景：本服务内含滑块验证所需的 Chromium。无头浏览器缺少 window.chrome 对象、
#       navigator.plugins 为空，会被平台识别为自动化环境导致滑块反复失败；
#       有头模式需要显示设备，容器内没有物理显示器，故用 Xvfb 提供虚拟屏幕。
# 停用方式：环境变量 XVFB_ENABLED=false 时不再拉起虚拟显示（此时恢复无头模式）。

set -e

XVFB_ENABLED="${XVFB_ENABLED:-true}"
# DISPLAY 编号与屏幕参数可由环境变量覆盖
DISPLAY_NUM="${DISPLAY_NUM:-99}"
XVFB_SCREEN="${XVFB_SCREEN:-1920x1080x24}"

if [ "$XVFB_ENABLED" = "true" ]; then
    echo "[entrypoint] 启动 Xvfb :${DISPLAY_NUM} 屏幕 ${XVFB_SCREEN}"
    Xvfb ":${DISPLAY_NUM}" -screen 0 "$XVFB_SCREEN" -nolisten tcp &
    XVFB_PID=$!

    # 等待虚拟显示就绪，避免浏览器抢先启动失败。
    # 检测 X socket 文件是否存在，不依赖 xdpyinfo 等额外工具。
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if [ -S "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
            break
        fi
        sleep 0.5
    done

    DISPLAY=":${DISPLAY_NUM}"
    export DISPLAY
    echo "[entrypoint] DISPLAY=${DISPLAY}（Xvfb pid=${XVFB_PID}）"
else
    echo "[entrypoint] Xvfb 已停用，按无头模式启动"
fi

exec python websocket/main.py
