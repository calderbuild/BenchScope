#!/bin/bash
# 飞书回调服务启动脚本

set -e

echo "🚀 启动飞书回调服务..."

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "❌ 错误: 找不到虚拟环境 (.venv 或 venv)"
    exit 1
fi

# 设置环境变量
export PYTHONPATH=.
export FLASK_ENV=production

# 检查环境变量
if [ -z "$FEISHU_APP_ID" ]; then
    echo "⚠️  警告: FEISHU_APP_ID 未设置"
fi

if [ -z "$FEISHU_APP_SECRET" ]; then
    echo "⚠️  警告: FEISHU_APP_SECRET 未设置"
fi

# 启动Flask服务 (生产环境使用gunicorn)
PORT=${PORT:-5000}
WORKERS=${WORKERS:-4}

echo "📡 服务地址: http://0.0.0.0:$PORT"
echo "🔧 工作进程: $WORKERS"
echo "📊 健康检查: http://localhost:$PORT/health"
echo ""

gunicorn -w $WORKERS \
    -b 0.0.0.0:$PORT \
    --timeout 30 \
    --access-logfile - \
    --error-logfile - \
    src.api.feishu_callback:app
