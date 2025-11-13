# 飞书回调服务部署指南

## 问题背景

**用户报错**: "加入候选池出错了，请稍后重试code:200340"

**原因分析**:
- 飞书卡片有"✅ 加入候选池"按钮
- 按钮点击后会调用回调服务
- 但Flask回调服务未实现（Phase 5 Task 5.2被跳过）
- 导致飞书收不到HTTP响应，返回200340错误码

## 解决方案

已实现完整的Flask回调服务 + 数据字段扩展：

1. **Flask回调服务** (`src/api/feishu_callback.py`)
   - 接收飞书卡片按钮点击事件
   - 验证签名（安全性）
   - URL去重检查
   - 返回友好提示

2. **飞书字段扩展** (`src/storage/feishu_storage.py`)
   - 新增9个字段：论文URL、GitHub Stars、作者信息、开源时间、复现脚本链接、评价指标摘要、数据集URL、任务类型、License类型
   - 自动填充已采集的数据

3. **数据模型更新** (`src/models.py`)
   - 扩展ScoredCandidate，支持新字段

---

## 部署步骤

### 1. 安装依赖

```bash
cd /mnt/d/VibeCoding_pgm/BenchScope
source .venv/bin/activate
pip install -r requirements.txt
```

新增依赖：
- `flask>=3.0.0`
- `gunicorn>=21.2.0`

### 2. 配置飞书Webhook密钥（可选）

编辑 `.env.local`：

```bash
# 飞书Webhook密钥（用于签名验证）
FEISHU_WEBHOOK_SECRET=your_webhook_secret_here
```

> **注意**: 如果不配置，签名验证会被跳过（开发环境可接受）

### 3. 启动回调服务

#### 方式A: 使用启动脚本（推荐）

```bash
# 生产环境（4个工作进程）
./scripts/start_callback_service.sh

# 或自定义端口和进程数
PORT=8000 WORKERS=2 ./scripts/start_callback_service.sh
```

#### 方式B: 直接运行

```bash
# 开发环境（单进程，支持热重载）
export PYTHONPATH=.
python src/api/feishu_callback.py

# 生产环境（多进程）
gunicorn -w 4 -b 0.0.0.0:5000 src.api.feishu_callback:app
```

服务启动后：
- 监听地址: `http://0.0.0.0:5000`
- 回调路径: `/feishu/callback`
- 健康检查: `/health`

### 4. 配置飞书卡片

在飞书开放平台配置卡片回调URL：

```
https://your-domain.com/feishu/callback
```

**内网测试**: 使用ngrok或frp内网穿透

```bash
# 使用ngrok（推荐）
ngrok http 5000

# 将ngrok提供的HTTPS地址配置到飞书
# 例如: https://abc123.ngrok.io/feishu/callback
```

### 5. 验证服务

```bash
# 健康检查
curl http://localhost:5000/health

# 预期响应:
# {"status":"ok","service":"BenchScope API"}
```

### 6. 测试回调功能

1. 运行Pipeline生成卡片消息：
   ```bash
   python src/main.py
   ```

2. 在飞书中点击"✅ 加入候选池"按钮

3. 预期行为：
   - ✅ 如果URL已存在 → 提示"该Benchmark已在候选池中"
   - ⚠️ 如果URL不存在 → 提示"请通过Pipeline重新采集此Benchmark"

---

## 当前实现限制

### 限制1: 仅支持已存在URL的去重检查

**原因**: 飞书卡片中携带的数据有限（仅URL），无法直接创建完整的ScoredCandidate记录

**解决方案（Phase 6+）**:
1. 在卡片中携带完整候选项JSON（通过value字段）
2. 或实现"待补充"状态 → 后续补充元数据

### 限制2: 新URL无法直接加入

**当前行为**: 点击新URL的"加入候选池"按钮会提示"请通过Pipeline重新采集"

**推荐流程**:
1. 用户在飞书中标记感兴趣的Benchmark
2. 管理员手动将URL添加到配置文件
3. 下次Pipeline运行时自动采集和评分

---

## 字段映射对照表

确保飞书多维表格中的字段名称与代码中的映射一致：

| 代码字段 | 飞书字段名称 | 数据类型 | 说明 |
|---------|------------|---------|------|
| title | 标题 | 文本 | ✅ |
| source | 来源 | 单选 | ✅ |
| url | URL | URL | ✅ |
| abstract | 摘要 | 文本 | ✅ |
| activity_score | 活跃度 | 数字 | ✅ |
| reproducibility_score | 可复现性 | 数字 | ✅ |
| license_score | 许可合规 | 数字 | ✅ |
| novelty_score | 任务新颖性 | 数字 | ✅ |
| relevance_score | MGX适配度 | 数字 | ✅ |
| total_score | 总分 | 数字 | ✅ |
| priority | 优先级 | 单选 | ✅ |
| reasoning | 评分依据 | 文本 | ✅ |
| status | 状态 | 单选 | ✅ |
| **paper_url** | **论文 URL** | **URL** | **✅ 新增** |
| **github_stars** | **GitHub Stars** | **数字** | **✅ 新增** |
| **authors** | **作者信息** | **文本** | **✅ 新增** |
| **publish_date** | **开源时间** | **日期** | **✅ 新增** |
| **reproduction_script_url** | **复现脚本链接** | **URL** | **✅ 新增** |
| **evaluation_metrics** | **评价指标摘要** | **文本** | **✅ 新增** |
| **dataset_url** | **数据集 URL** | **URL** | **✅ 新增** |
| **task_type** | **任务类型** | **单选** | **✅ 新增** |

**字段类型说明**:
- **URL**: 飞书URL类型，代码中需要使用 `{"link": "..."}` 格式
- **日期**: 代码中使用 `YYYY-MM-DD` 格式字符串
- **数字**: 直接传递数值
- **文本**: 字符串（建议限制长度）

---

## 测试验证

### 1. 运行Pipeline测试新字段

```bash
python src/main.py
```

检查日志中是否有新字段写入成功的提示。

### 2. 查看飞书多维表格

访问飞书多维表格，验证新字段是否有数据填充：
- GitHub Stars: 应显示数字（如果是GitHub来源）
- 作者信息: 应显示作者列表（arXiv论文）
- 开源时间: 应显示日期（YYYY-MM-DD格式）
- 数据集 URL: 应显示链接（如果采集到）

### 3. 测试回调功能

```bash
# 发送测试请求
curl -X POST http://localhost:5000/feishu/callback \
  -H "Content-Type: application/json" \
  -d '{
    "action": {
      "value": {
        "action": "approve",
        "candidate_url": "https://github.com/test/repo"
      }
    },
    "open_id": "ou_test123"
  }'

# 预期响应:
# {"toast":{"type":"warning","content":"⚠️ 请通过Pipeline重新采集此Benchmark"}}
```

---

## 故障排查

### 问题1: 回调服务启动失败

**检查环境变量**:
```bash
echo $FEISHU_APP_ID
echo $FEISHU_APP_SECRET
```

**检查端口占用**:
```bash
lsof -i :5000
```

### 问题2: 飞书卡片按钮点击无响应

**检查日志**:
```bash
# 查看Flask日志
tail -f logs/flask.log
```

**检查网络连接**:
- 确保服务可公网访问（或使用ngrok内网穿透）
- 确保飞书回调URL配置正确

### 问题3: 新字段未填充数据

**检查数据模型**:
- 确认 `ScoredCandidate` 有新字段定义
- 确认字段有默认值或在初始化时赋值

**检查采集器**:
- GitHub采集器应填充 `github_stars`
- arXiv采集器应填充 `authors` 和 `publish_date`

---

## 多人协作提示

### 问题: 多个用户同时点击"加入候选池"

**当前行为**:
- 第一个用户: 可能成功添加（取决于实现）
- 后续用户: 会收到"已在候选池中"提示

**建议**:
- 使用飞书多维表格的"记录权限"功能
- 或在卡片中显示"已有X人加入"计数

---

## 未来改进方向

### Phase 6+:
1. **卡片携带完整数据**: 在value中传递完整ScoredCandidate JSON
2. **待补充状态**: 允许先加入"待补充"记录，后续补充元数据
3. **多人协作提示**: 显示"已有X人感兴趣"
4. **自动优先级调整**: 根据点击次数自动提升优先级

---

## 相关文档

- Flask回调服务代码: `src/api/feishu_callback.py`
- 飞书存储实现: `src/storage/feishu_storage.py`
- 数据模型定义: `src/models.py`
- Phase 6 PRD: `.claude/specs/benchmark-intelligence-agent/PHASE6-EXPANSION-PRD.md`

---

**文档生成时间**: 2025-11-13
**负责人**: Claude Code
**状态**: ✅ 已部署可用
