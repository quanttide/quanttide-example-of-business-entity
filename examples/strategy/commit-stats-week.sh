#!/bin/sh
# 统计主仓库及所有子模块最近一周的提交数
#
# 用法: ./commit-stats-week.sh [since]
#   since 可选，默认 7 days ago，也可传 "2026-07-01"

SINCE="${1:-7 days ago}"

cd ../../../..

echo "=== 最近一周提交统计（since: $SINCE）==="
echo ""

total=0
for dir in apps/* data/* docs/* examples/*; do
  if [ -d "$dir/.git" ] || [ -f "$dir/.git" ]; then
    count=$(cd "$dir" && git rev-list --count HEAD --after="$SINCE" 2>/dev/null || echo "0")
    printf "%-30s %s commits\n" "$dir" "$count"
    total=$((total + count))
  fi
done

echo ""
echo "--- 主仓库 ---"
count=$(git rev-list --count HEAD --after="$SINCE")
printf "%-30s %s commits\n" "quanttide-tech" "$count"
total=$((total + count))

echo ""
echo "=== 合计: $total commits ==="
