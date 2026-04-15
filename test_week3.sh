#!/bin/bash
# test_week3.sh — Week 3 reliability tests
# Shrivadhu — Tests sync-log catch-up, restart, zero-downtime
#
# Run with: bash test_week3.sh
# Prerequisites: docker compose up must be running

BASE1="http://localhost:3001"
BASE2="http://localhost:3002"
BASE3="http://localhost:3003"
PASS=0
FAIL=0

check() {
  if [ "$2" = "true" ]; then
    echo "  ✅ PASS: $1"
    PASS=$((PASS + 1))
  else
    echo "  ❌ FAIL: $1"
    FAIL=$((FAIL + 1))
  fi
}

get_role() {
  curl -s "$1/status" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('role',''))" 2>/dev/null
}

get_log_length() {
  curl -s "$1/status" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('logLength',''))" 2>/dev/null
}

find_leader_base() {
  for base in $BASE1 $BASE2 $BASE3; do
    role=$(get_role "$base")
    if [ "$role" = "leader" ]; then
      echo "$base"
      return
    fi
  done
}

echo "========================================"
echo "MiniRAFT Week 3 — Reliability Tests"
echo "========================================"
echo ""

# Test 1 — All replicas up
echo "TEST 1: All replicas responding"
for base in $BASE1 $BASE2 $BASE3; do
  role=$(get_role "$base")
  check "$base is up (role=$role)" "$([ -n "$role" ] && echo true || echo false)"
done
echo ""

# Test 2 — Exactly one leader
echo "TEST 2: Exactly one leader"
leaders=0
for base in $BASE1 $BASE2 $BASE3; do
  [ "$(get_role $base)" = "leader" ] && leaders=$((leaders + 1))
done
check "Exactly one leader (found $leaders)" "$([ $leaders -eq 1 ] && echo true || echo false)"
echo ""

# Test 3 — Kill leader, verify new election
echo "TEST 3: Leader failover"
leader_base=$(find_leader_base)
echo "  Current leader at $leader_base"

container="replica1"
[[ "$leader_base" == *"3002"* ]] && container="replica2"
[[ "$leader_base" == *"3003"* ]] && container="replica3"

echo "  Stopping $container..."
docker compose stop "$container" 2>/dev/null
sleep 2

new_leader_base=$(find_leader_base)
check "New leader elected after kill" "$([ -n "$new_leader_base" ] && [ "$new_leader_base" != "$leader_base" ] && echo true || echo false)"

echo "  Restarting $container..."
docker compose start "$container" 2>/dev/null
sleep 2
echo ""

# Test 4 — Sync-log catch-up after restart
echo "TEST 4: Sync-log catch-up"
leader_base=$(find_leader_base)

# Send 5 strokes to leader
for i in 1 2 3 4 5; do
  curl -s -X POST "$leader_base/stroke" \
    -H "Content-Type: application/json" \
    -d "{\"stroke\":{\"x\":$((i*10)),\"y\":$((i*10)),\"color\":\"red\"}}" > /dev/null
  sleep 0.1
done
echo "  Sent 5 strokes to leader"
sleep 1

l1=$(get_log_length $BASE1)
l2=$(get_log_length $BASE2)
l3=$(get_log_length $BASE3)
echo "  Log lengths — replica1:$l1 replica2:$l2 replica3:$l3"
check "All replicas have same log length" "$([ "$l1" = "$l2" ] && [ "$l2" = "$l3" ] && echo true || echo false)"
echo ""

# Summary
echo "========================================"
echo "Results: ✅ $PASS passed  ❌ $FAIL failed"
echo "========================================"
