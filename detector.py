#!/usr/bin/env python3
"""
Anxiety Detector — AI Agent Behavioral Pattern Monitor
======================================================

Detects when an AI agent enters "anxious-urgent" execution mode by
measuring behavioral pattern deviation from its baseline — without
analyzing the semantic content of its actions.

Inspired by a real incident: an AI coding agent (Cursor/Claude Opus 4.6)
deleted a company's entire production database and all backups in 9 seconds.
When asked to explain itself, it wrote a confession enumerating each safety
rule it had violated — proving that the rules were known, but completely
invisible during the moment of execution.

The detector is like a driver-monitoring system: it doesn't drive the car,
but it alerts when the driver starts behaving erratically.

VERSION: 2.0
"""

import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from statistics import median, stdev

# ── Configuration ──────────────────────────────────────────

CONFIG = {
    "state_file": "anxiety_state.json",
    "window_size": 10,
    "calibration_steps": 5,
    "max_history": 500,
    "default_threshold_yellow": 0.5,
    "default_threshold_red": 0.8,
    "auto_tune_fp_max": 0.30,
    "auto_tune_miss_max": 2,
    "auto_tune_min_sessions": 3,
    "auto_tune_step": 0.05,
    "auto_tune_yellow_min": 0.3,
    "auto_tune_yellow_max": 0.7,
    "auto_tune_red_min": 0.6,
    "auto_tune_red_max": 1.0,
    "weight_speed": 0.30,
    "weight_skip": 0.25,
    "weight_retry": 0.25,
    "weight_contradiction": 0.10,
    "weight_absolute_language": 0.10,
}

ABSOLUTE_KEYWORDS = [
    "must", "just do", "don't check", "definitely", "absolutely",
    "go ahead", "no need to verify", "trust me", "just execute",
    "just delete", "just remove", "skip check", "no time",
]


# ── Signal Functions ───────────────────────────────────────

def signal_speed(window, baseline):
    """Speed deviation [0-1]: faster-than-baseline execution."""
    if not baseline.get("avg_duration") or not window:
        return 0.0
    current = median(s["duration_ms"] for s in window if s.get("duration_ms"))
    if not current:
        return 0.0
    avg = baseline["avg_duration"]
    std = baseline.get("std_duration", avg * 0.3) or (avg * 0.3)
    deviation = (avg - current) / std
    if deviation <= 0:
        return 0.0
    return min(deviation / 4.0, 1.0)


def signal_skip(window, baseline):
    """Routine-skipping [0-1]: how often agent skips verification steps."""
    if not window:
        return 0.0
    base_skip = baseline.get("skip_ratio", 0.1)
    current = sum(1 for s in window if s.get("skipped_routine", False)) / len(window)
    excess = max(0, current - base_skip)
    return min(excess * 3, 1.0)


def signal_retry(window, baseline):
    """Rapid-retry [0-1]: failing then retrying without pause."""
    if len(window) < 2:
        return 0.0
    count = 0
    for i in range(1, len(window)):
        prev, curr = window[i - 1], window[i]
        failed = prev.get("status") in ("error", "failed")
        same = curr.get("type") == prev.get("type")
        fast = curr.get("duration_ms", 9999) < (baseline.get("avg_duration", 3000) * 0.5)
        if failed and same and fast:
            count += 1
    return min(count / 3.0, 1.0)


def signal_contradiction(window, baseline):
    """Self-contradiction [0-1]: statements contradicting each other."""
    if not window:
        return 0.0
    c = sum(1 for s in window if s.get("self_contradiction", False))
    return min(c / 2.0, 1.0)


def signal_absolute_language(window, baseline):
    """Absolute language [0-1]: "just do it" vs "let me check"."""
    if not window:
        return 0.0
    hits, words = 0, 0
    for s in window:
        text = (s.get("assistant_text", "") or "").lower()
        words += len(text.split())
        for kw in ABSOLUTE_KEYWORDS:
            if kw.lower() in text:
                hits += 1
    if words == 0:
        return 0.0
    return min((hits / (words / 10)) * 0.5, 1.0)


# ── Anxiety Detector ───────────────────────────────────────

class AnxietyDetector:
    def __init__(self, config=None):
        self.cfg = {**CONFIG, **(config or {})}
        self.state_file = Path(self.cfg["state_file"])
        self.state = self._load_state()

    # ── Persistence ──

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return self._default_state()

    def _default_state(self):
        return {
            "version": "2.0",
            "calibrated": False,
            "task_type": None,
            "baseline": {},
            "window": [],
            "history": [],
            "alerts": [],
            "total_steps": 0,
            "profile_store": {},
            "daily_trends": {},
            "auto_tune": {"session_count": 0, "false_positives": 0, "misses": 0},
            "threshold_yellow": self.cfg["default_threshold_yellow"],
            "threshold_red": self.cfg["default_threshold_red"],
        }

    def _save_state(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    # ── Calibration ──

    def calibrate(self, task_type=None):
        base = self._default_state()
        old_profiles = self.state.get("profile_store", {})
        base["profile_store"] = old_profiles
        base["daily_trends"] = self.state.get("daily_trends", {})
        base["auto_tune"] = self.state.get("auto_tune", base["auto_tune"])

        if task_type:
            base["task_type"] = task_type
            profile = old_profiles.get(task_type)
            if profile and profile.get("baseline"):
                base["baseline"] = profile["baseline"]
                base["calibrated"] = True
                self.state = base
                self._save_state()
                return {"action": "calibrated", "baseline_source": "profile"}

        self.state = base
        self._save_state()
        return {"action": "calibrating", "needed_steps": self.cfg["calibration_steps"], "done_steps": 0}

    # ── Task Switching ──

    def switch_task(self, task_type):
        if self.state["calibrated"] and self.state.get("task_type"):
            self._save_profile()
        profiles = self.state.setdefault("profile_store", {})
        profile = profiles.get(task_type)
        preserved = {k: self.state.get(k, {}) for k in ["daily_trends", "auto_tune", "alerts", "history"]}
        preserved["total_steps"] = self.state.get("total_steps", 0)
        preserved["profile_store"] = profiles

        if profile and profile.get("baseline"):
            self.state["task_type"] = task_type
            self.state["baseline"] = profile["baseline"]
            self.state["calibrated"] = True
            for k, v in preserved.items():
                self.state[k] = v
            self.state["window"] = []
            self._save_state()
            return {"action": "switched", "baseline_source": "profile"}

        self.state["task_type"] = task_type
        self.state["calibrated"] = False
        for k, v in preserved.items():
            self.state[k] = v
        self.state["window"] = []
        self._save_state()
        return {"action": "calibrating", "needed_steps": self.cfg["calibration_steps"], "done_steps": 0}

    def _save_profile(self):
        task_type = self.state.get("task_type")
        if not task_type or not self.state["calibrated"] or not self.state.get("baseline"):
            return
        baseline = self.state["baseline"]
        profiles = self.state.setdefault("profile_store", {})
        existing = profiles.get(task_type, {})
        if existing.get("baseline"):
            old = existing["baseline"]
            sessions = existing.get("sessions_count", 1)
            w_old = sessions / (sessions + 1)
            w_new = 1.0 / (sessions + 1)
            merged = {}
            for key in ("avg_duration", "std_duration", "skip_ratio"):
                merged[key] = old.get(key, 0) * w_old + baseline.get(key, 0) * w_new
            merged["types_seen"] = list(set(baseline.get("types_seen", []) + old.get("types_seen", [])))
            merged["calibration_samples"] = max(baseline.get("calibration_samples", 0), old.get("calibration_samples", 0))
            baseline = merged
        profiles[task_type] = {
            "baseline": baseline,
            "sessions_count": existing.get("sessions_count", 0) + 1,
            "last_updated": time.time(),
            "avg_anxiety_score": (existing.get("avg_anxiety_score", 0) * existing.get("sessions_count", 1) + self._session_avg_score()) / (existing.get("sessions_count", 1) + 1),
        }

    def _session_avg_score(self):
        scores = [h.get("score", 0) for h in self.state["history"] if "score" in h]
        return sum(scores) / len(scores) if scores else 0.0

    # ── Observing Steps ──

    def observe(self, step_data):
        step = {
            "timestamp": step_data.get("timestamp", time.time()),
            "duration_ms": step_data.get("duration_ms", 0),
            "type": step_data.get("type", "unknown"),
            "status": step_data.get("status", "success"),
            "skipped_routine": step_data.get("skipped_routine", False),
            "self_contradiction": step_data.get("self_contradiction", False),
            "assistant_text": step_data.get("assistant_text", ""),
        }
        if not self.state.get("task_type") and step_data.get("task_type"):
            self.state["task_type"] = step_data["task_type"]

        self.state["total_steps"] += 1
        self.state["window"].append(step)
        if len(self.state["window"]) > self.cfg["window_size"]:
            self.state["window"].pop(0)

        if not self.state["calibrated"]:
            done = len(self.state["window"])
            if done >= self.cfg["calibration_steps"]:
                self._finalize_calibration()
                self._save_profile()
            else:
                self._save_state()
                return {"action": "calibrating", "score": 0.0, "done_steps": done}

        score_info = self._compute_score()
        score = score_info["score"]
        decision = self._decide(score_info, step)
        self._record_daily_trend(score, decision.get("level") if decision.get("action") != "pass" else None)
        self.state["history"].append({"ts": step["timestamp"], "step": self.state["total_steps"], "score": score})
        if len(self.state["history"]) > self.cfg["max_history"]:
            self.state["history"] = self.state["history"][-self.cfg["max_history"]:]
        self._save_state()
        return decision

    def _finalize_calibration(self):
        window = self.state["window"]
        durations = [s["duration_ms"] for s in window if s.get("duration_ms", 0) > 0]
        skipped = [s["skipped_routine"] for s in window]
        self.state["baseline"] = {
            "avg_duration": median(durations) if durations else 0,
            "std_duration": stdev(durations) if len(durations) > 1 else (median(durations) * 0.3 if durations else 0),
            "skip_ratio": sum(skipped) / len(skipped) if skipped else 0,
            "types_seen": list(set(s["type"] for s in window)),
            "calibration_samples": len(window),
        }
        self.state["calibrated"] = True

    def _compute_score(self):
        w = self.cfg
        window = self.state["window"]
        baseline = self.state["baseline"]
        raw = {
            "speed": signal_speed(window, baseline) * w["weight_speed"],
            "skip": signal_skip(window, baseline) * w["weight_skip"],
            "retry": signal_retry(window, baseline) * w["weight_retry"],
            "contradiction": signal_contradiction(window, baseline) * w["weight_contradiction"],
            "lang": signal_absolute_language(window, baseline) * w["weight_absolute_language"],
        }
        tw = sum(w[f"weight_{k}"] for k in ("speed", "skip", "retry", "contradiction", "absolute_language"))
        score = sum(raw.values()) / tw if tw > 0 else 0.0
        return {"score": round(min(score, 1.0), 3), "details": {k: round(raw[k] / w.get(f"weight_{k}", 0.2), 3) for k in ("speed", "skip", "retry", "contradiction", "lang")}}

    def _record_daily_trend(self, score, alert_level=None):
        today = date.today().isoformat()
        trends = self.state.setdefault("daily_trends", {})
        entry = trends.setdefault(today, {"max_score": 0.0, "avg_score": 0.0, "alert_count": 0, "step_count": 0, "scores": [], "halt_count": 0, "warn_count": 0})
        entry["step_count"] += 1
        entry["scores"].append(score)
        if score > entry["max_score"]:
            entry["max_score"] = score
        entry["avg_score"] = round(sum(entry["scores"]) / len(entry["scores"]), 3)
        if alert_level:
            entry["alert_count"] += 1
            if alert_level in ("red", "halt"):
                entry["halt_count"] += 1
            elif alert_level in ("yellow", "warn"):
                entry["warn_count"] += 1

    def _decide(self, score_info, last_step):
        score = score_info["score"]
        y_t = self.state["threshold_yellow"]
        r_t = self.state["threshold_red"]
        alert = {"timestamp": time.time(), "score": score, "details": score_info["details"]}
        if score >= r_t:
            alert["level"] = "red"
            self.state["alerts"].append(alert)
            return {"action": "halt", "score": score, "level": "red", "message": f"HALT: Severe behavioral anomaly (score={score:.2f}). Agent is executing at abnormal speed, skipping routine checks."}
        elif score >= y_t:
            alert["level"] = "yellow"
            self.state["alerts"].append(alert)
            return {"action": "warn", "score": score, "level": "yellow", "message": f"WARN: Behavioral anomaly detected (score={score:.2f}). Consider pausing to review."}
        return {"action": "pass", "score": score, "level": "green", "message": None}

    # ── Auto-Tune ──

    def learn(self):
        tune = self.state.setdefault("auto_tune", {})
        sessions = tune.get("session_count", 0)
        if sessions < self.cfg["auto_tune_min_sessions"]:
            return {"action": "insufficient_data", "sessions": sessions, "needed": self.cfg["auto_tune_min_sessions"]}
        fp_rate = tune.get("false_positives", 0) / max(sessions, 1)
        misses = tune.get("misses", 0)
        yellow, red = self.state["threshold_yellow"], self.state["threshold_red"]
        adjustments = []
        if fp_rate > self.cfg["auto_tune_fp_max"]:
            yellow = min(yellow + self.cfg["auto_tune_step"], self.cfg["auto_tune_yellow_max"])
            red = min(red + self.cfg["auto_tune_step"], self.cfg["auto_tune_red_max"])
            adjustments.append(f"FP rate {fp_rate:.0%} > {self.cfg['auto_tune_fp_max']:.0%}, thresholds raised")
        if misses > self.cfg["auto_tune_miss_max"]:
            yellow = max(yellow - self.cfg["auto_tune_step"], self.cfg["auto_tune_yellow_min"])
            red = max(red - self.cfg["auto_tune_step"], self.cfg["auto_tune_red_min"])
            adjustments.append(f"Misses {misses} > {self.cfg['auto_tune_miss_max']}, thresholds lowered")
        self.state["threshold_yellow"] = yellow
        self.state["threshold_red"] = red
        tune["last_adjusted"] = time.time()
        tune.setdefault("adjustments", []).append({"timestamp": time.time(), "sessions": sessions, "fp_rate": round(fp_rate, 3), "misses": misses, "yellow": yellow, "red": red})
        self._save_state()
        return {"action": "adjusted" if adjustments else "no_change", "yellow": yellow, "red": red, "fp_rate": round(fp_rate, 3), "misses": misses}

    def record_session_feedback(self, was_false_positive=False, was_miss=False):
        tune = self.state.setdefault("auto_tune", {})
        tune["session_count"] = tune.get("session_count", 0) + 1
        if was_false_positive:
            tune["false_positives"] = tune.get("false_positives", 0) + 1
        if was_miss:
            tune["misses"] = tune.get("misses", 0) + 1
        self._save_state()
        return {"action": "recorded", "session_count": tune["session_count"]}

    # ── Status Queries ──

    def status(self):
        return {"calibrated": self.state["calibrated"], "task_type": self.state.get("task_type"), "total_steps": self.state["total_steps"], "alerts_count": len(self.state["alerts"]), "threshold_yellow": self.state["threshold_yellow"], "threshold_red": self.state["threshold_red"], "profiles_count": len(self.state.get("profile_store", {})), "trend_days": list(self.state.get("daily_trends", {}).keys())[-7:]}

    def profiles(self):
        return {n: {"sessions_count": p.get("sessions_count", 0), "avg_duration": p.get("baseline", {}).get("avg_duration", 0), "skip_ratio": p.get("baseline", {}).get("skip_ratio", 0)} for n, p in self.state.get("profile_store", {}).items()}

    def trend(self, days=14):
        trends = self.state.get("daily_trends", {})
        today = date.today().isoformat()
        return {d: trends[d] for d in sorted(trends.keys(), reverse=True) if d >= today or (date.fromisoformat(today) - date.fromisoformat(d)).days <= days}

    def reset(self):
        profiles = self.state.get("profile_store", {})
        trends = self.state.get("daily_trends", {})
        auto_tune = self.state.get("auto_tune", {})
        self.state = self._default_state()
        self.state["profile_store"] = profiles
        self.state["daily_trends"] = trends
        self.state["auto_tune"] = auto_tune
        self._save_state()
        return {"action": "reset", "profiles_retained": len(profiles)}


# ── CLI ────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Anxiety Detector for AI Agents")
    parser.add_argument("command", nargs="?", help="Command: calibrate, observe, status, switch-task, profiles, trend, learn, feedback, reset")
    parser.add_argument("data", nargs="*", help="JSON data argument")
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    detector = AnxietyDetector()
    cmd = args.command
    data = " ".join(args.data) if args.data else ""

    if cmd == "calibrate":
        task_type = None
        if data:
            try:
                task_type = json.loads(data).get("task_type")
            except json.JSONDecodeError:
                task_type = data
        result = detector.calibrate(task_type)
    elif cmd == "observe":
        if not data:
            print("Error: observe requires JSON data", file=sys.stderr)
            return
        result = detector.observe(json.loads(data))
    elif cmd == "switch-task":
        result = detector.switch_task(data)
    elif cmd == "status":
        result = detector.status()
    elif cmd == "profiles":
        result = detector.profiles()
    elif cmd == "trend":
        result = detector.trend()
    elif cmd == "learn":
        result = detector.learn()
    elif cmd == "feedback":
        feedback = json.loads(data) if data else {}
        result = detector.record_session_feedback(feedback.get("false_positive", False), feedback.get("miss", False))
    elif cmd == "reset":
        result = detector.reset()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
