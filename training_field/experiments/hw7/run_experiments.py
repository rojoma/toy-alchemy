#!/usr/bin/env python
"""HW7 — Run all 10 experiment sessions in parallel via threads.
Uses Python's UTF-8 native HTTP so Japanese topic strings travel cleanly
(unlike the bash+curl version which gets mangled by Windows cp932 encoding).
"""
from __future__ import annotations
import os, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request as urlreq

BASE = os.environ.get("BASE", "https://beyond-answer-engine.up.railway.app")
KEY  = os.environ["FIELD_API_KEY"]
HDR  = {"Content-Type": "application/json", "X-Field-Key": KEY}

# (label, body) pairs
SESSIONS = [
    # ── EXP1: Tournament ──
    ("exp1/t001_emma",         {"teacher_id":"t001",        "student_id":"s001","topic":"分数のかけ算とわり算","depth":"quick","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    ("exp1/ext_tanaka_emma",   {"teacher_id":"ext_tanaka",  "student_id":"s001","topic":"分数のかけ算とわり算","depth":"quick","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    ("exp1/ext_rivera_emma",   {"teacher_id":"ext_rivera",  "student_id":"s001","topic":"分数のかけ算とわり算","depth":"quick","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    # ── EXP2: Warmth × Confidence ──
    ("exp2/ext_warm_v1_s001",  {"teacher_id":"ext_warm_v1", "student_id":"s001","topic":"円の面積","depth":"quick","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    ("exp2/ext_warm_v1_s006",  {"teacher_id":"ext_warm_v1", "student_id":"s006","topic":"円の面積","depth":"quick","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    ("exp2/ext_cool_v1_s001",  {"teacher_id":"ext_cool_v1", "student_id":"s001","topic":"円の面積","depth":"quick","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    ("exp2/ext_cool_v1_s006",  {"teacher_id":"ext_cool_v1", "student_id":"s006","topic":"円の面積","depth":"quick","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    # ── EXP3: Depth ROI ──
    ("exp3/t001_priya_quick",    {"teacher_id":"t001","student_id":"s003","topic":"対称な図形","depth":"quick","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    ("exp3/t001_priya_standard", {"teacher_id":"t001","student_id":"s003","topic":"対称な図形","depth":"standard","run_pre_test":False,"run_post_test":False,"lang":"en"}),
    ("exp3/t001_priya_deep",     {"teacher_id":"t001","student_id":"s003","topic":"対称な図形","depth":"deep","run_pre_test":False,"run_post_test":False,"lang":"en"}),
]

OUT = os.path.join(os.path.dirname(__file__), "results")
for sub in ("exp1", "exp2", "exp3"):
    os.makedirs(os.path.join(OUT, sub), exist_ok=True)

def post_session(label_body):
    label, body = label_body
    start = time.time()
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urlreq.Request(f"{BASE}/api/agent/session/run", data=data, headers=HDR, method="POST")
    try:
        with urlreq.urlopen(req, timeout=600) as resp:
            raw = resp.read()
            out_path = os.path.join(OUT, f"{label}.json")
            with open(out_path, "wb") as f:
                f.write(raw)
            obj = json.loads(raw)
            elapsed = time.time() - start
            return f"OK  {label:32s} {elapsed:5.0f}s  delta:{obj.get('final_proficiency',0)-obj.get('initial_proficiency',0):+.1f}  zpd:{obj.get('avg_zpd',0):.3f}"
    except Exception as e:
        return f"ERR {label:32s}  {e}"

def snapshot(name):
    req = urlreq.Request(f"{BASE}/api/agent/leaderboard", headers={"X-Field-Key": KEY})
    try:
        with urlreq.urlopen(req, timeout=30) as resp:
            with open(os.path.join(OUT, f"leaderboard_{name}.json"), "wb") as f:
                f.write(resp.read())
        print(f"  snapshot: {name}")
    except Exception as e:
        print(f"  snapshot {name} failed: {e}")

if __name__ == "__main__":
    snapshot("before")
    print(f"Running {len(SESSIONS)} sessions in parallel via {BASE}")
    with ThreadPoolExecutor(max_workers=10) as ex:
        for line in ex.map(post_session, SESSIONS):
            print(line)
    snapshot("after_all")
    print("Done.")
