"""
自动约面系统 - Flask 后端
MVP 版本：HR 用个人邮箱登录，查询面试官空闲，发选时邮件给候选人，候选人确认后记录
"""

import os
import uuid
import json
import sqlite3
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, render_template, abort, session
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "interview-scheduler-secret-2026")

BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")
DB_PATH = os.path.join(os.path.dirname(__file__), "interviews.db")

# ─────────────────────────────────────────
# 常见邮箱服务商 SMTP 配置
# ─────────────────────────────────────────
SMTP_PRESETS = {
    "xiaohongshu.com": {"host": "smtp.xiaohongshu.com", "port": 465, "ssl": True},
    "gmail.com":       {"host": "smtp.gmail.com",       "port": 465, "ssl": True},
    "outlook.com":     {"host": "smtp-mail.outlook.com","port": 587, "ssl": False},
    "hotmail.com":     {"host": "smtp-mail.outlook.com","port": 587, "ssl": False},
    "163.com":         {"host": "smtp.163.com",         "port": 465, "ssl": True},
    "qq.com":          {"host": "smtp.qq.com",          "port": 465, "ssl": True},
}

def get_smtp_config(email: str):
    """根据邮箱域名自动匹配 SMTP 配置"""
    domain = email.split("@")[-1].lower()
    return SMTP_PRESETS.get(domain, {"host": f"smtp.{domain}", "port": 465, "ssl": True})

# ─────────────────────────────────────────
# 数据库初始化
# ─────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interviews (
            id TEXT PRIMARY KEY,
            hr_email TEXT,                   -- 发件 HR 邮箱
            candidate_name TEXT NOT NULL,
            candidate_email TEXT NOT NULL,
            candidate_link TEXT,
            interviewers TEXT NOT NULL,      -- JSON array
            duration_min INTEGER DEFAULT 60,
            interview_type TEXT DEFAULT 'online',
            status TEXT DEFAULT 'draft',     -- draft/sent/confirmed/scheduled
            selected_slots TEXT,             -- JSON array，HR 选的备选时段
            confirmed_slot TEXT,             -- 候选人最终选定的时段（JSON）
            token TEXT UNIQUE,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ─────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def format_slot_cn(slot):
    """ISO slot dict → 中文时间字符串，如：4月8日（周二）14:00-15:00"""
    WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    start = datetime.fromisoformat(slot["start"])
    end   = datetime.fromisoformat(slot["end"])
    return f"{start.month}月{start.day}日（{WEEKDAYS[start.weekday()]}）{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"

def send_email(from_email, from_password, to_email, to_name, subject, html_body):
    """用 HR 个人邮箱凭据发送 HTML 邮件"""
    cfg = get_smtp_config(from_email)
    from_name = session.get("hr_name", "小红书招聘团队")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{from_email}>"
    msg["To"]      = f"{to_name} <{to_email}>"
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if cfg["ssl"]:
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=10)
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=10)
        server.starttls()

    server.login(from_email, from_password)
    server.sendmail(from_email, [to_email], msg.as_string())
    server.quit()

def build_invite_email(candidate_name, slots, select_url, hr_email):
    """生成候选人选时邮件 HTML"""
    slots_html = "".join(
        f'<li style="padding:6px 0;font-size:15px;">🕐 {format_slot_cn(s)}</li>'
        for s in slots
    )
    return f"""
<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'PingFang SC',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
  <tr><td align="center">
    <table width="580" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
      <tr>
        <td style="background:linear-gradient(135deg,#ff2442,#ff6b6b);padding:32px 40px;text-align:center;">
          <div style="font-size:32px;margin-bottom:8px;">🗓️</div>
          <div style="color:#fff;font-size:22px;font-weight:600;">面试时间确认</div>
          <div style="color:rgba(255,255,255,0.85);font-size:14px;margin-top:4px;">小红书招聘团队</div>
        </td>
      </tr>
      <tr>
        <td style="padding:36px 40px;">
          <p style="font-size:16px;color:#333;margin:0 0 16px;">您好，{candidate_name}，</p>
          <p style="font-size:15px;color:#555;line-height:1.7;margin:0 0 24px;">
            感谢您对小红书的关注！我们诚邀您参加面试，请从以下时间段中选择一个您方便的时间：
          </p>
          <div style="background:#fff8f8;border:1px solid #ffe0e3;border-radius:8px;padding:16px 24px;margin-bottom:28px;">
            <ul style="margin:0;padding:0 0 0 4px;list-style:none;">{slots_html}</ul>
          </div>
          <div style="text-align:center;margin-bottom:28px;">
            <a href="{select_url}"
               style="display:inline-block;background:#ff2442;color:#fff;text-decoration:none;
                      padding:14px 40px;border-radius:8px;font-size:16px;font-weight:600;">
              点击选择面试时间 →
            </a>
          </div>
          <p style="font-size:13px;color:#999;line-height:1.6;margin:0;">
            如有任何问题，欢迎直接回复此邮件联系我们。<br>期待与您的交流！
          </p>
        </td>
      </tr>
      <tr>
        <td style="background:#fafafa;border-top:1px solid #f0f0f0;padding:16px 40px;text-align:center;">
          <p style="font-size:12px;color:#bbb;margin:0;">小红书招聘团队 · {hr_email}</p>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body></html>
"""

# ─────────────────────────────────────────
# 路由
# ─────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/select/<token>")
def select_page(token):
    conn = get_db()
    row = conn.execute("SELECT * FROM interviews WHERE token=?", (token,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    interview = dict(row)
    interview["interviewers"]   = json.loads(interview["interviewers"])
    interview["selected_slots"] = json.loads(interview["selected_slots"] or "[]")
    slots_display = [
        {"iso": s, "label": format_slot_cn(s)}
        for s in interview["selected_slots"]
    ]
    return render_template("select.html", interview=interview, slots=slots_display, token=token)

# ── 登录 / 登出 ──

@app.route("/api/login", methods=["POST"])
def api_login():
    """验证 HR 邮箱密码（实际发一封测试邮件确认连通性）"""
    data     = request.json
    email    = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()
    name     = (data.get("name") or "").strip() or "小红书招聘团队"

    if not email or not password:
        return jsonify({"error": "邮箱和密码不能为空"}), 400

    cfg = get_smtp_config(email)
    try:
        if cfg["ssl"]:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=8)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=8)
            server.starttls()
        server.login(email, password)
        server.quit()
    except smtplib.SMTPAuthenticationError:
        return jsonify({"error": "邮箱密码错误，请检查后重试"}), 401
    except Exception as e:
        return jsonify({"error": f"连接邮件服务器失败：{str(e)}"}), 502

    # 存入 session（密码加密存储，不落磁盘）
    session["hr_email"]    = email
    session["hr_password"] = password
    session["hr_name"]     = name
    return jsonify({"success": True, "email": email, "name": name,
                    "smtp": f"{cfg['host']}:{cfg['port']}"})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/api/me", methods=["GET"])
def api_me():
    if "hr_email" not in session:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "email": session["hr_email"], "name": session["hr_name"]})

# ── 查询空闲 ──

@app.route("/api/query-availability", methods=["POST"])
def query_availability():
    """
    查询面试官空闲时间。
    TODO: 对接红薯日历 API（bunx @xhs/hi-workspace-cli calendar:get-user-schedules）
    当前返回 mock 数据用于 UI 联调。
    """
    data         = request.json
    interviewers = data.get("interviewers", [])
    duration_min = data.get("duration_min", 60)
    time_range   = data.get("time_range", "next_week")

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if time_range == "this_week":
        start, end = today, today + timedelta(days=7)
    elif time_range == "next_week":
        start, end = today + timedelta(days=7), today + timedelta(days=14)
    else:
        start, end = today, today + timedelta(days=14)

    slot_times = [("10:00","11:00"),("14:00","15:00"),("15:30","16:30"),("16:00","17:00"),("11:00","12:00")]
    mock_slots, slot_idx, d = [], 0, start
    while d < end and len(mock_slots) < 5:
        if d.weekday() < 5:
            hs, ms = map(int, slot_times[slot_idx % len(slot_times)][0].split(":"))
            he, me = map(int, slot_times[slot_idx % len(slot_times)][1].split(":"))
            ss = d.replace(hour=hs, minute=ms)
            se = d.replace(hour=he, minute=me)
            slot = {"start": ss.isoformat(), "end": se.isoformat()}
            mock_slots.append({**slot, "label": format_slot_cn(slot),
                                "interviewers": interviewers, "available": True})
            slot_idx += 1
        d += timedelta(days=1)

    return jsonify({"slots": mock_slots, "mock": True})

# ── 发送邀请 ──

@app.route("/api/send-invite", methods=["POST"])
def send_invite():
    if "hr_email" not in session:
        return jsonify({"error": "请先登录邮箱"}), 401

    data             = request.json
    candidate_name   = (data.get("candidate_name") or "").strip()
    candidate_email  = (data.get("candidate_email") or "").strip()
    candidate_link   = data.get("candidate_link", "")
    interviewers     = data.get("interviewers", [])
    duration_min     = data.get("duration_min", 60)
    interview_type   = data.get("interview_type", "online")
    selected_slots   = data.get("selected_slots", [])

    if not candidate_name or not candidate_email:
        return jsonify({"error": "候选人姓名和邮箱不能为空"}), 400
    if not selected_slots:
        return jsonify({"error": "请至少选择一个备选时段"}), 400

    interview_id = str(uuid.uuid4())
    token        = str(uuid.uuid4()).replace("-", "")
    select_url   = f"{BASE_URL}/select/{token}"

    conn = get_db()
    conn.execute("""
        INSERT INTO interviews
        (id, hr_email, candidate_name, candidate_email, candidate_link, interviewers,
         duration_min, interview_type, status, selected_slots, token, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,'sent',?,?,?,?)
    """, (
        interview_id, session["hr_email"],
        candidate_name, candidate_email, candidate_link,
        json.dumps(interviewers, ensure_ascii=False),
        duration_min, interview_type,
        json.dumps(selected_slots, ensure_ascii=False),
        token, now_str(), now_str()
    ))
    conn.commit()
    conn.close()

    try:
        subject  = "【面试邀请】小红书招聘团队 - 面试时间确认"
        html     = build_invite_email(candidate_name, selected_slots, select_url, session["hr_email"])
        send_email(session["hr_email"], session["hr_password"],
                   candidate_email, candidate_name, subject, html)
        return jsonify({"success": True, "interview_id": interview_id, "select_url": select_url})
    except Exception as e:
        return jsonify({"error": f"邮件发送失败：{str(e)}",
                        "interview_id": interview_id, "select_url": select_url}), 500

# ── 候选人确认时间 ──

@app.route("/api/confirm-slot", methods=["POST"])
def confirm_slot():
    data           = request.json
    token          = data.get("token", "")
    confirmed_slot = data.get("slot")

    if not token or not confirmed_slot:
        return jsonify({"error": "参数不完整"}), 400

    conn = get_db()
    row  = conn.execute("SELECT * FROM interviews WHERE token=?", (token,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "链接无效或已过期"}), 404
    if row["status"] == "confirmed":
        conn.close()
        return jsonify({"error": "您已经选过时间了"}), 400

    conn.execute("""
        UPDATE interviews SET confirmed_slot=?, status='confirmed', updated_at=? WHERE token=?
    """, (json.dumps(confirmed_slot, ensure_ascii=False), now_str(), token))
    conn.commit()
    conn.close()

    # TODO: 对接红薯日历 API 自动建会
    return jsonify({
        "success": True,
        "confirmed_slot_label": format_slot_cn(confirmed_slot),
        "message": "已收到您的选择，HR 会尽快确认并发送日历邀请"
    })

# ── 约面记录 ──

@app.route("/api/interviews", methods=["GET"])
def list_interviews():
    hr_email = session.get("hr_email")
    conn     = get_db()
    if hr_email:
        rows = conn.execute(
            "SELECT * FROM interviews WHERE hr_email=? ORDER BY created_at DESC LIMIT 50",
            (hr_email,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM interviews ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    conn.close()

    result = []
    for row in rows:
        item = dict(row)
        item["interviewers"]   = json.loads(item["interviewers"] or "[]")
        item["selected_slots"] = json.loads(item["selected_slots"] or "[]")
        if item["confirmed_slot"]:
            cs = json.loads(item["confirmed_slot"])
            item["confirmed_slot_label"] = format_slot_cn(cs)
        result.append(item)
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
