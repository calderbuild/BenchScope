#!/bin/bash
# 飞书回调服务启动脚本

set -e

echo "========================================="
echo "启动BenchScope飞书回调服务"
echo "========================================="

# 激活虚拟环境
source .venv/bin/activate

# 设置环境变量
export PYTHONPATH=.

# 安装Flask依赖（如果尚未安装）
if ! python -c "import flask" 2>/dev/null; then
    echo "安装Flask依赖..."
    pip install flask gunicorn
fi

# 开发环境：使用Flask内置服务器
# python src/api/feishu_callback.py

# 生产环境：使用gunicorn（推荐）
echo "启动gunicorn服务器..."
echo "监听地址: 0.0.0.0:5000"
echo "访问地址: http://localhost:5000/health"
echo "回调地址: http://your-domain.com:5000/feishu/callback"
echo ""
echo "使用Ctrl+C停止服务"
echo "========================================="

gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 4 \
    --timeout 30 \
    --access-logfile logs/api_access.log \
    --error-logfile logs/api_error.log \
    --log-level info \
    src.api.feishu_callback:app
