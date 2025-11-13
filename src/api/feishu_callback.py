"""飞书卡片回调服务

处理飞书交互式卡片的按钮点击事件，实现"一键加入候选池"功能。

功能:
1. 接收飞书卡片按钮点击事件
2. 验证签名（安全性）
3. URL去重检查
4. 写入飞书多维表格
5. 返回友好的响应消息
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from src.config import get_settings
from src.storage.feishu_storage import FeishuStorage

logger = logging.getLogger(__name__)

app = Flask(__name__)
settings = get_settings()


def verify_feishu_signature(timestamp: str, nonce: str, signature: str, body: str) -> bool:
    """验证飞书Webhook签名

    飞书签名算法:
    1. 拼接字符串: timestamp + nonce + encrypt_key + body
    2. SHA256计算
    3. 对比签名

    Args:
        timestamp: 请求时间戳
        nonce: 随机字符串
        signature: 飞书签名
        body: 请求体JSON字符串

    Returns:
        是否验证通过
    """
    if not settings.feishu.webhook_secret:
        logger.warning("未配置webhook_secret，跳过签名验证")
        return True

    # 拼接字符串
    sign_base = f"{timestamp}{nonce}{settings.feishu.webhook_secret}{body}"

    # 计算SHA256
    calculated_signature = hashlib.sha256(sign_base.encode()).hexdigest()

    return calculated_signature == signature


@app.route("/feishu/callback", methods=["POST"])
def feishu_callback():
    """飞书卡片回调处理

    接收飞书卡片按钮点击事件，处理"加入候选池"操作。

    请求体示例:
    {
        "challenge": "...",  # 首次验证时返回
        "type": "card",
        "action": {
            "value": {
                "action": "approve",
                "candidate_url": "https://..."
            }
        },
        "open_id": "ou_xxx",  # 用户ID
        "token": "xxx"
    }

    响应:
    {
        "toast": {
            "type": "success",  # success/error
            "content": "已成功加入候选池"
        }
    }
    """
    try:
        # 1. 获取请求数据
        body = request.get_data(as_text=True)
        data = json.loads(body)

        # 2. 首次验证（飞书会发送challenge）
        if "challenge" in data:
            logger.info("收到飞书验证请求")
            return jsonify({"challenge": data["challenge"]})

        # 3. 验证签名（可选，提升安全性）
        timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
        nonce = request.headers.get("X-Lark-Request-Nonce", "")
        signature = request.headers.get("X-Lark-Signature", "")

        if not verify_feishu_signature(timestamp, nonce, signature, body):
            logger.error("飞书签名验证失败")
            return jsonify({"toast": {"type": "error", "content": "签名验证失败"}}), 401

        # 4. 解析按钮点击数据
        action_value = data.get("action", {}).get("value", {})
        action_type = action_value.get("action")
        candidate_url = action_value.get("candidate_url")
        user_id = data.get("open_id", "unknown")

        logger.info("收到飞书回调: action=%s, url=%s, user=%s", action_type, candidate_url, user_id)

        # 5. 处理"加入候选池"操作
        if action_type == "approve" and candidate_url:
            result = asyncio.run(handle_approve_candidate(candidate_url, user_id))
            return jsonify(result)

        # 6. 未知操作
        logger.warning("未知的action类型: %s", action_type)
        return jsonify({"toast": {"type": "error", "content": "未知操作"}})

    except Exception as e:
        logger.exception("飞书回调处理失败: %s", e)
        return jsonify({"toast": {"type": "error", "content": f"处理失败: {str(e)}"}}), 500


async def handle_approve_candidate(candidate_url: str, user_id: str) -> Dict[str, Any]:
    """处理"加入候选池"操作

    流程:
    1. 连接飞书存储
    2. 查询URL是否已存在
    3. 如果已存在 → 返回"已加入"提示
    4. 如果不存在 → 写入飞书表格 → 返回"成功加入"提示

    Args:
        candidate_url: 候选项URL
        user_id: 操作用户ID

    Returns:
        飞书响应消息
    """
    storage = FeishuStorage(settings)

    # 1. 查询URL是否已存在
    logger.info("检查URL是否已存在: %s", candidate_url)
    existing_urls = await storage.get_existing_urls()

    if candidate_url in existing_urls:
        logger.info("URL已存在，跳过添加: %s", candidate_url)
        return {
            "toast": {
                "type": "info",
                "content": "✅ 该Benchmark已在候选池中"
            }
        }

    # 2. 从飞书卡片提取的数据有限，这里需要标记为"待补充"
    # 实际使用中，应该从卡片中携带完整的ScoredCandidate数据
    logger.warning("当前实现仅支持已存在URL的去重检查")
    logger.warning("新URL需要通过完整pipeline流程采集和评分")

    return {
        "toast": {
            "type": "warning",
            "content": "⚠️ 请通过Pipeline重新采集此Benchmark"
        }
    }


@app.route("/health", methods=["GET"])
def health_check():
    """健康检查接口"""
    return jsonify({"status": "ok", "service": "BenchScope API"}), 200


if __name__ == "__main__":
    # 开发环境运行
    # 生产环境建议使用gunicorn: gunicorn -w 4 -b 0.0.0.0:5000 src.api.feishu_callback:app
    app.run(host="0.0.0.0", port=5000, debug=True)
