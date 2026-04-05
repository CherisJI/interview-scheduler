"""
自动约面系统 - Flask 后端
MVP 版本：支持 HR 输入面试官+候选人，查询空闲时间，发送选时邮件，候选人确认时间
"""

import os
import uuid
import json
import sqlite3
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, render_template, abort
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")

BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")
DB_PATH = os.path.join(os.path.dirname(__file__), "interviews.db")

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
            candidate_name TEXT NOT NULL,
            candidate_email TEXT NOT NULL,
            candidate_link TEXT,
            interviewers TEXT NOT NULL,      -- JSON array
            duration_min INTEGER DEFAULT 60,
            interview_type TEXT DEFAULT 'online',
            status TEXT DEFAULT 'draft',     -- draft/sent/confirmed/scheduled
            selected_slots TEXT,             -- JSON array，HR 选的备选时段
            confirmed_slot TEXT,             -- 候选人最终选定的时段
            token TEXT UNIQUE,               -- 候选人选时页面的访问 token
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

def format_slot_cn(slot_iso):
    """把 ISO 时间格式转成中文友好格式，如：4月8日（周二）14:00-15:00"""
    WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    start_str, end_str = slot_iso["start"], slot_iso["end"]
    start = datetime.fromisoformat(start_str)
    end = datetime.fromisoformat(end_str)
    weekday = WEEKDAYS[start.weekday()]
    return f"{start.month}月{start.day}日（{weekday}）{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"

def send_email(to_email, to_name, subject, html_body):
    """发送 HTML 邮件，SMTP 配置从环境变量读取"""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    from_name = os.getenv("SMTP_FROM_NAME", "小红书招聘团队")

    if not smtp_host or not smtp_user or not smtp_password:
        raise ValueError("邮件配置不完整，请检查 .env 中的 SMTP_HOST / SMTP_USER / SMTP_PASSWORD")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{smtp_user}>"
    msg["To"] = f"{to_name} <{to_email}>"
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [to_email], msg.as_string())

def build_invite_email(candidate_name, slots, select_url):
    """生成发给候选人的选时邮件 HTML"""
    slots_html = ""
    for s in slots:
        label = format_slot_cn(s)
        slots_html += f'<li style="padding:6px 0;font-size:15px;">🕐 {label}</li>'

    return f"""
<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'PingFang SC',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <!-- 头部 -->
        <tr>
          <td style="background:linear-gradient(135deg,#ff2442,#ff6b6b);padding:32px 40px;text-align:center;">
            <div style="font-size:32px;margin-bottom:8px;">🗓️</div>
            <div style="color:#fff;font-size:22px;font-weight:600;">面试时间确认</div>
            <div style="color:rgba(255,255,255,0.85);font-size:14px;margin-top:4px;">小红书招聘团队</div>
          </td>
        </tr>
        <!-- 正文 -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="font-size:16px;color:#333;margin:0 0 16px;">您好，{candidate_name}，</p>
            <p style="font-size:15px;color:#555;line-height:1.7;margin:0 0 24px;">
              感谢您对小红书的关注！我们诚邀您参加面试，请从以下时间段中选择一个您方便的时间：
            </p>
            <!-- 时间列表 -->
            <div style="background:#fff8f8;border:1px solid #ffe0e3;border-radius:8px;padding:16px 24px;margin-bottom:28px;">
              <ul style="margin:0;padding:0 0 0 4px;list-style:none;">
                {slots_html}
              </ul>
            </div>
            <!-- 选时按钮 -->
            <div style="text-align:center;margin-bottom:28px;">
              <a href="{select_url}"
                 style="display:inline-block;background:#ff2442;color:#fff;text-decoration:none;
                        padding:14px 40px;border-radius:8px;font-size:16px;font-weight:600;
                        letter-spacing:0.5px;">
                点击选择面试时间 →
              </a>
            </div>
            <p style="font-size:13px;color:#999;line-height:1.6;margin:0;">
              如有任何问题，欢迎直接回复此邮件联系我们。<br>
              期待与您的交流！
            </p>
          </td>
        </tr>
        <!-- 底部 -->
        <tr>
          <td style="background:#fafafa;border-top:1px solid #f0f0f0;padding:16px 40px;text-align:center;">
            <p style="font-size:12px;color:#bbb;margin:0;">小红书招聘团队 · jisiming@xiaohongshu.com</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
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
    interview["interviewers"] = json.loads(interview["interviewers"])
    interview["selected_slots"] = json.loads(interview["selected_slots"] or "[]")
    # 格式化时间供前端显示
    slots_display = [
        {"iso": s, "label": format_slot_cn(s)}
        for s in interview["selected_slots"]
    ]
    return render_template("select.html", interview=interview, slots=slots_display, token=token)

@app.route("/api/query-availability", methods=["POST"])
def query_availability():
    """
    查询面试官空闲时间。
    TODO: 对接红薯日历 API（bunx @xhs/hi-workspace-cli calendar:get-user-schedules）
    当前返回 mock 数据用于 UI 联调。
    """
    data = request.json
    interviewers = data.get("interviewers", [])
    duration_min = data.get("duration_min", 60)
    time_range = data.get("time_range", "this_week")  # this_week / next_week / two_weeks

    # 计算时间范围
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if time_range == "this_week":
        start = today
        end = today + timedelta(days=7)
    elif time_range == "next_week":
        start = today + timedelta(days=7)
        end = today + timedelta(days=14)
    else:
        start = today
        end = today + timedelta(days=14)

    # ── Mock 数据：模拟工作日的空闲时段 ──
    WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    mock_slots = []
    slot_times = [("10:00", "11:00"), ("14:00", "15:00"), ("15:30", "16:30"), ("16:00", "17:00"), ("11:00", "12:00")]
    slot_idx = 0
    d = start
    while d < end and len(mock_slots) < 5:
        if d.weekday() < 5:  # 只取工作日
            t_start, t_end = slot_times[slot_idx % len(slot_times)]
            h_s, m_s = map(int, t_start.split(":"))
            h_e, m_e = map(int, t_end.split(":"))
            slot_start = d.replace(hour=h_s, minute=m_s)
            slot_end = d.replace(hour=h_e, minute=m_e)
            mock_slots.append({
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
                "label": format_slot_cn({"start": slot_start.isoformat(), "end": slot_end.isoformat()}),
                "interviewers": interviewers,
                "available": True
            })
            slot_idx += 1
        d += timedelta(days=1)

    return jsonify({"slots": mock_slots, "mock": True})

@app.route("/api/send-invite", methods=["POST"])
def send_invite():
    """发送候选人选时邮件，并在数据库中创建约面记录"""
    data = request.json
    candidate_name = data.get("candidate_name", "").strip()
    candidate_email = data.get("candidate_email", "").strip()
    candidate_link = data.get("candidate_link", "")
    interviewers = data.get("interviewers", [])
    duration_min = data.get("duration_min", 60)
    interview_type = data.get("interview_type", "online")
    selected_slots = data.get("selected_slots", [])  # 已是 ISO 格式的 slot list

    if not candidate_name or not candidate_email:
        return jsonify({"error": "候选人姓名和邮箱不能为空"}), 400
    if not selected_slots:
        return jsonify({"error": "请至少选择一个备选时段"}), 400

    # 生成唯一 token 和 ID
    interview_id = str(uuid.uuid4())
    token = str(uuid.uuid4()).replace("-", "")
    select_url = f"{BASE_URL}/select/{token}"

    # 写入数据库
    conn = get_db()
    conn.execute("""
        INSERT INTO interviews
        (id, candidate_name, candidate_email, candidate_link, interviewers,
         duration_min, interview_type, status, selected_slots, token, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,'sent',?,?,?,?)
    """, (
        interview_id, candidate_name, candidate_email, candidate_link,
        json.dumps(interviewers, ensure_ascii=False),
        duration_min, interview_type,
        json.dumps(selected_slots, ensure_ascii=False),
        token, now_str(), now_str()
    ))
    conn.commit()
    conn.close()

    # 发送邮件
    try:
        subject = f"【面试邀请】小红书招聘团队 - 面试时间确认"
        html_body = build_invite_email(candidate_name, selected_slots, select_url)
        send_email(candidate_email, candidate_name, subject, html_body)
        return jsonify({"success": True, "interview_id": interview_id, "select_url": select_url})
    except ValueError as e:
        # SMTP 未配置，返回 select_url 供测试用
        return jsonify({
            "success": False,
            "warning": str(e),
            "interview_id": interview_id,
            "select_url": select_url,
            "tip": "邮件未发送（SMTP 未配置），可直接用 select_url 测试候选人选时页面"
        })
    except Exception as e:
        return jsonify({"error": f"邮件发送失败：{str(e)}"}), 500

@app.route("/api/confirm-slot", methods=["POST"])
def confirm_slot():
    """候选人提交所选时间"""
    data = request.json
    token = data.get("token", "")
    confirmed_slot = data.get("slot")  # ISO 格式的单个 slot

    if not token or not confirmed_slot:
        return jsonify({"error": "参数不完整"}), 400

    conn = get_db()
    row = conn.execute("SELECT * FROM interviews WHERE token=?", (token,)).fetchone()
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

    interview = dict(row)
    conn.close()

    slot_label = format_slot_cn(confirmed_slot)

    # TODO: 对接红薯日历 API，自动给面试官创建日程
    # bunx @xhs/hi-workspace-cli calendar:create --help

    return jsonify({
        "success": True,
        "confirmed_slot_label": slot_label,
        "message": "已收到您的选择，HR 会尽快确认并发送日历邀请"
    })

@app.route("/api/interviews", methods=["GET"])
def list_interviews():
    """获取约面记录列表"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM interviews ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        item["interviewers"] = json.loads(item["interviewers"] or "[]")
        item["selected_slots"] = json.loads(item["selected_slots"] or "[]")
        if item["confirmed_slot"]:
            item["confirmed_slot"] = json.loads(item["confirmed_slot"])
        result.append(item)
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
