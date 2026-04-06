const http = require('http');
const { execSync } = require('child_process');
const path = require('path');

const CALENDAR_SKILL = path.join(process.env.HOME, '.openclaw/workspace/skills/calendar');
const PORT = 3099;

// 查询用户ID
function searchUser(name) {
  const result = execSync(
    `cd "${CALENDAR_SKILL}" && PATH="/home/node/.npm-global/bin:$PATH" bash run.sh search-users "${name}" --format json`,
    { encoding: 'utf8', timeout: 30000 }
  );
  const data = JSON.parse(result);
  const users = data?.subscribeUserVoList || data?.result?.users || [];
  if (!users.length) return null;
  const u = users[0];
  return { userId: u.userId || u.userID, userName: u.userName || u.name };
}

// 查询用户日程
function querySchedules(userId, beginTime, endTime) {
  const result = execSync(
    `cd "${CALENDAR_SKILL}" && PATH="/home/node/.npm-global/bin:$PATH" bash run.sh query-user-schedules --user-ids ${userId} --begin-time "${beginTime}" --end-time "${endTime}" --format json`,
    { encoding: 'utf8', timeout: 30000 }
  );
  return JSON.parse(result);
}

// 计算空闲时段（10:30-21:00，30分钟间隔）
function calcFreeSlots(schedules, beginDate, endDate, durationMin = 30) {
  const freeSlots = [];
  const workStart = 10 * 60 + 30; // 10:30 in minutes
  const workEnd = 21 * 60;         // 21:00 in minutes

  // 遍历每一天（以北京时间为准）
  let d = new Date(beginDate);
  const end = new Date(endDate);
  while (d <= end) {
    // 取北京时间的日期字符串 YYYY-MM-DD
    const bjOffset = 8 * 60 * 60 * 1000;
    const bjDate = new Date(d.getTime() + bjOffset);
    const dateStr = bjDate.toISOString().split('T')[0]; // e.g. "2026-04-07"
    const dayOfWeek = bjDate.getUTCDay();

    if (dayOfWeek !== 0 && dayOfWeek !== 6) { // 跳过周末
      // 找这一天的已有日程（schedules的startTime格式为 "2026-04-07 10:00:00" 北京时间）
      const dayBusy = (schedules || []).filter(s => {
        return s.startTime && s.startTime.startsWith(dateStr);
      }).map(s => ({
        // 直接把 "2026-04-07 10:00:00" 当北京时间解析
        start: new Date(s.startTime.replace(' ', 'T') + '+08:00'),
        end: new Date(s.endTime.replace(' ', 'T') + '+08:00')
      }));

      // 从10:30开始，每30分钟一个时段（用北京时间构造）
      let t = workStart;
      while (t + durationMin <= workEnd) {
        // 构造北京时间的时段
        const slotStart = new Date(`${dateStr}T${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}:00+08:00`);
        const slotEnd = new Date(slotStart.getTime() + durationMin * 60 * 1000);

        // 检查是否与已有日程冲突
        const conflict = dayBusy.some(b => slotStart < b.end && slotEnd > b.start);
        if (!conflict && slotStart > new Date()) {
          freeSlots.push({
            start: slotStart.toISOString(),
            end: slotEnd.toISOString()
          });
        }
        t += 30;
      }
    }
    d.setDate(d.getDate() + 1);
  }
  return freeSlots;
}

const server = http.createServer((req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'OPTIONS') { res.writeHead(200); res.end(); return; }

  const url = new URL(req.url, `http://localhost:${PORT}`);

  // GET /free-slots?interviewer=天雪&days=7&duration=30
  if (url.pathname === '/free-slots' && req.method === 'GET') {
    const interviewer = url.searchParams.get('interviewer');
    const days = parseInt(url.searchParams.get('days') || '14');
    const duration = parseInt(url.searchParams.get('duration') || '30');

    if (!interviewer) {
      res.writeHead(400);
      res.end(JSON.stringify({ error: '请提供面试官姓名' }));
      return;
    }

    try {
      // 搜用户
      const user = searchUser(interviewer);
      if (!user) {
        res.writeHead(404);
        res.end(JSON.stringify({ error: `找不到用户：${interviewer}` }));
        return;
      }

      // 查日程
      const now = new Date();
      const beginTime = now.toISOString().replace('Z', '+08:00').replace(/\.\d+/, '');
      const endDate = new Date(now);
      endDate.setDate(endDate.getDate() + days);
      const endTime = endDate.toISOString().replace('Z', '+08:00').replace(/\.\d+/, '');

      const data = querySchedules(user.userId, beginTime, endTime);
      const schedules = (data?.events || []).map(e => ({
        startTime: e.start.replace(' ', 'T') + '+08:00',
        endTime: e.end.replace(' ', 'T') + '+08:00'
      }));

      // 计算空闲
      const freeSlots = calcFreeSlots(schedules, now, endDate, duration);

      res.writeHead(200);
      res.end(JSON.stringify({
        interviewer: user.userName,
        userId: user.userId,
        freeSlots: freeSlots.slice(0, 20) // 最多返回20个
      }));

    } catch (e) {
      res.writeHead(500);
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // 健康检查
  if (url.pathname === '/health') {
    res.writeHead(200);
    res.end(JSON.stringify({ status: 'ok' }));
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: 'Not found' }));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`日历 API 服务已启动：http://localhost:${PORT}`);
});
