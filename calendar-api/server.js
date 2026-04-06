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
  return { userId: u.userId, userName: u.name || u.userName };
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

  // 遍历每一天
  let d = new Date(beginDate);
  const end = new Date(endDate);
  while (d <= end) {
    const dayOfWeek = d.getDay();
    if (dayOfWeek !== 0 && dayOfWeek !== 6) { // 跳过周末
      const dateStr = d.toISOString().split('T')[0];

      // 找这一天的已有日程
      const dayBusy = (schedules || []).filter(s => {
        return s.startTime && s.startTime.startsWith(dateStr);
      }).map(s => ({
        start: new Date(s.startTime),
        end: new Date(s.endTime)
      }));

      // 从10:30开始，每30分钟一个时段
      let t = workStart;
      while (t + durationMin <= workEnd) {
        const slotStart = new Date(d);
        slotStart.setHours(Math.floor(t / 60), t % 60, 0, 0);
        const slotEnd = new Date(slotStart);
        slotEnd.setMinutes(slotEnd.getMinutes() + durationMin);

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
