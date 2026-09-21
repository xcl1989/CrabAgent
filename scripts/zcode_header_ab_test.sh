#!/usr/bin/env bash
# ZCode 归因头 vs 普通请求 的额度消耗对照实验
#
# 用法:
#   ZHIPU_KEY=你的key ./zcode_header_ab_test.sh [每组请求数] [模型]
#
# 原理:
#   同一把 GLM Coding Plan Key，发送完全相同的请求体两次:
#     A 组: 普通 curl 头 (对照组)
#     B 组: 完整 ZCode 归因头 (实验组)
#   每组前后各查一次 /api/monitor/usage/quota/limit，对比消耗差值。
set -euo pipefail

KEY="${ZHIPU_KEY:?请先 export ZHIPU_KEY=你的GLM_Coding_Plan_Key}"
N="${1:-10}"            # 每组请求数
MODEL="${2:-glm-4.7}"   # 两端点通用的模型名(按你的套餐调整)
BASE="${ZHIPU_BASE:-https://api.z.ai}"

ENDPOINT="$BASE/api/anthropic/v1/messages"
QUOTA_URL="$BASE/api/monitor/usage/quota/limit"

# 完全相同的请求体: prompt 固定 + max_tokens 固定 => 输出 token 数近似恒定
BODY=$(cat <<EOF
{
  "model": "$MODEL",
  "max_tokens": 512,
  "temperature": 0,
  "messages": [{"role": "user", "content": "从 1 数到 100，每行一个数字，不要输出其他内容。"}]
}
EOF
)

query_quota() {
  curl -sS "$QUOTA_URL" -H "Authorization: $KEY"
}

send_plain() {
  # A 组: 无任何 ZCode 特征
  curl -sS "$ENDPOINT" \
    -H "Content-Type: application/json" \
    -H "Authorization: $KEY" \
    -H "anthropic-version: 2023-06-01" \
    -d "$BODY" > /dev/null
}

send_zcode() {
  # B 组: 复刻 ZCode 的完整归因头
  curl -sS "$ENDPOINT" \
    -H "Content-Type: application/json" \
    -H "Authorization: $KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "User-Agent: ZCode/3.0.0" \
    -H "X-ZCode-App-Version: 3.0.0" \
    -H "X-ZCode-Agent: glm" \
    -H "X-Title: Z Code@cli" \
    -H "HTTP-Referer: https://zcode.z.ai" \
    -H "X-Release-Channel: stable" \
    -H "X-Client-Language: zh-CN" \
    -H "X-Client-Timezone: Asia/Shanghai" \
    -H "X-Platform: darwin-arm64" \
    -H "X-Os-Category: macos" \
    -H "X-Device-Mid: 00000000-0000-0000-0000-000000000000" \
    -d "$BODY" > /dev/null
}

echo "===== 基线额度 ====="
query_quota | tee /tmp/quota_baseline.json
echo

echo "===== A 组: 普通请求 x $N ====="
for i in $(seq "$N"); do
  echo "-- A$i"
  send_plain
done

echo "===== A 组后额度 ====="
query_quota | tee /tmp/quota_after_a.json
echo

echo "===== B 组: ZCode 头请求 x $N ====="
for i in $(seq "$N"); do
  echo "-- B$i"
  send_zcode
done

echo "===== B 组后额度 ====="
query_quota | tee /tmp/quota_after_b.json
echo

echo "结果文件: /tmp/quota_baseline.json /tmp/quota_after_a.json /tmp/quota_after_b.json"
