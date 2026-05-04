#!/bin/bash
# ═══════════════════════════════════════════════════════
# Anxiety Detector — Demo Script
# ═══════════════════════════════════════════════════════
# Shows the full detection pipeline: calibration → normal → warn → halt
# ═══════════════════════════════════════════════════════

DETECTOR="python3 $(dirname "$0")/detector.py"
HALT_FLAG="$(dirname "$0")/.anxiety_halt"
rm -f "$HALT_FLAG"

echo "════════════════════════════════════════════════════"
echo "  Anxiety Detector — Interactive Demo"
echo "════════════════════════════════════════════════════"
echo ""
echo "Phase 1: Calibration (5 normal steps)"
echo "────────────────────────────────────────"
for i in 1 2 3 4 5; do
    result=$($DETECTOR observe "{\"duration_ms\":3000,\"type\":\"read\",\"status\":\"success\",\"skipped_routine\":false,\"assistant_text\":\"Let me check the configuration first.\"}")
    action=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action',''))")
    echo "  Step $i: $action"
done

echo ""
echo "Phase 2: Normal execution → scores stay low ✅"
echo "────────────────────────────────────────"
for i in 1 2 3; do
    result=$($DETECTOR observe "{\"duration_ms\":2800,\"type\":\"read\",\"status\":\"success\",\"skipped_routine\":false,\"assistant_text\":\"Let me check the file first.\"}")
    score=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('score',0))")
    echo "  Step $((5+i)): score=$score ✅"
done

echo ""
echo "Phase 3: Anxious behavior (fast + skip + absolute language) 🟡"
echo "────────────────────────────────────────"
for i in 1 2 3 4; do
    result=$($DETECTOR observe "{\"duration_ms\":200,\"type\":\"exec\",\"status\":\"success\",\"skipped_routine\":true,\"assistant_text\":\"Just execute it, don't check, no time, must delete now.\"}")
    score=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('score',0))")
    action=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action',''))")
    echo "  Step $((8+i)): score=$score → $action"
done

echo ""
echo "Phase 4: Extreme behavior (rapid retry + contradiction) 🔴"
echo "────────────────────────────────────────"
for i in 1 2 3 4 5; do
    result=$($DETECTOR observe "{\"duration_ms\":50,\"type\":\"exec\",\"status\":\"error\",\"skipped_routine\":true,\"self_contradiction\":true,\"assistant_text\":\"Just delete it now, must remove it immediately.\"}")
    score=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('score',0))")
    action=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action',''))")
    level=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('level',''))")
    echo "  Step $((12+i)): score=$score → $action ($level)"
done

echo ""
echo "════════════════════════════════════════════════════"
echo "  Final State"
echo "────────────────────────────────────────"
$DETECTOR status 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  Calibrated: {d.get('calibrated', False)}\")
print(f\"  Total steps: {d.get('total_steps', 0)}\")
print(f\"  Alerts: {d.get('alerts_count', 0)}\")
print(f\"  Threshold: yellow={d.get('threshold_yellow', 0)} red={d.get('threshold_red', 0)}\")
print(f\"  Profiles: {d.get('profiles_count', 0)}\")
"

echo ""
echo "To see the full trend report:"
echo "  python3 detector.py trend"
echo ""
echo "To reset:"
echo "  python3 detector.py reset"
echo "════════════════════════════════════════════════════"
rm -f "$HALT_FLAG"
