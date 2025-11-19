#!/bin/bash
# Codex 完成情况快速验证脚本
# 使用方法: bash scripts/quick_validation.sh

set -e  # 遇到错误立即退出

echo "========================================"
echo "Codex 任务完成情况快速验证"
echo "========================================"
echo ""

# 激活环境
echo "[1/6] 激活虚拟环境..."
source .venv/bin/activate
export PYTHONPATH=.

# 检查PwC是否完全移除
echo ""
echo "[2/6] 验证PwC采集器是否完全移除..."
if grep -q "PWC" src/common/constants.py; then
    echo "❌ 失败: constants.py中仍存在PWC常量"
    exit 1
fi

if [ -f "src/collectors/pwc_collector.py" ]; then
    echo "❌ 失败: pwc_collector.py文件仍存在"
    exit 1
fi

if grep -q "PwC" src/collectors/__init__.py; then
    echo "❌ 失败: __init__.py中仍有PwC导入"
    exit 1
fi

echo "✅ 通过: PwC采集器已完全移除"

# 检查GitHub预筛选常量
echo ""
echo "[3/6] 验证GitHub预筛选常量..."
if grep -q "PREFILTER_MIN_GITHUB_STARS.*10" src/common/constants.py; then
    echo "✅ 通过: stars阈值已降低到10"
else
    echo "❌ 失败: stars阈值未更新"
    exit 1
fi

if grep -q "PREFILTER_MIN_README_LENGTH.*500" src/common/constants.py; then
    echo "✅ 通过: README长度阈值已设置为500"
else
    echo "❌ 失败: README长度阈值未设置"
    exit 1
fi

if grep -q "PREFILTER_RECENT_DAYS.*90" src/common/constants.py; then
    echo "✅ 通过: 最近更新阈值已设置为90天"
else
    echo "❌ 失败: 最近更新阈值未设置"
    exit 1
fi

# 检查时间窗口常量
echo ""
echo "[4/6] 验证时间窗口常量..."
if grep -q "GITHUB_LOOKBACK_DAYS.*30" src/common/constants.py; then
    echo "✅ 通过: GitHub时间窗口已设置为30天"
else
    echo "❌ 失败: GitHub时间窗口未设置"
    exit 1
fi

# 检查核心脚本
echo ""
echo "[5/6] 验证核心脚本..."
if [ -f "scripts/analyze_logs.py" ]; then
    echo "✅ 通过: analyze_logs.py已创建"
else
    echo "❌ 失败: analyze_logs.py不存在"
    exit 1
fi

if [ -f "scripts/deduplicate_feishu_table.py" ]; then
    echo "✅ 通过: deduplicate_feishu_table.py已创建"
else
    echo "❌ 失败: deduplicate_feishu_table.py不存在"
    exit 1
fi

if [ -f "scripts/sync_sqlite_to_feishu.py" ]; then
    echo "✅ 通过: sync_sqlite_to_feishu.py已创建"
else
    echo "❌ 失败: sync_sqlite_to_feishu.py不存在"
    exit 1
fi

# 检查GitHub Actions与版本监控状态
echo ""
echo "[6/6] 验证GitHub Actions与版本监控下线..."
if [ -f ".github/workflows/daily_collect.yml" ]; then
    echo "✅ 通过: daily_collect.yml存在"
else
    echo "❌ 失败: daily_collect.yml不存在"
    exit 1
fi

if [ -f ".github/workflows/track_releases.yml" ]; then
    echo "❌ 失败: 版本监控workflow仍然存在"
    exit 1
fi

if [ -d "src/tracker" ] || [ -f "scripts/track_github_releases.py" ] || [ -f "scripts/track_arxiv_versions.py" ]; then
    echo "❌ 失败: 版本监控代码尚未完全移除"
    exit 1
fi

echo "✅ 通过: 版本监控相关代码已下线"

# 总结
echo ""
echo "========================================"
echo "快速验证完成！"
echo "========================================"
echo ""
echo "✅ 所有基础检查通过"
echo ""
echo "下一步建议："
echo "1. 运行完整pipeline测试: python -m src.main"
echo "2. 运行单元测试: pytest tests/unit/ -v"
echo "3. 检查飞书表格与Webhook推送结果"
echo "4. Git提交代码（参考 docs/codex-completion-report.md）"
echo ""
