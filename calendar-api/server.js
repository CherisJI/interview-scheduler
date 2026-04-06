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
// schedules 里 startTime/endTime 格式为 "2026-04-07 11:00:00+08:00"
function calcFreeSlots(schedules, days, durationMin = 30) {
  const freeSlots = [];
  const now = new Date();

  // 构建日程的忙碌时间数组（全部转为 Date 对象）
  const busyTimes = (schedules || []).map(s => ({
    start: new Date(s.startTime.replace(' ', 'T')),
    end:   new Date(s.endTime.replace(' ', 'T'))
  }));

  // 遍历未来 days 天（从今天开始）
  for (let i = 0; i <= days; i++) {
    // 构造北京时间当天日期字符串
    const bjNow = new Date(now.getTime() + 8 * 3600 * 1000);
    const bjDay = new Date(bjNow);
    bjDay.setUTCDate(bjDay.getUTCDate() + i);
    const dateStr = bjDay.toISOString().split('T')[0]; // "2026-04-07"
    const dow = bjDay.getUTCDay(); // 0=Sun, 6=Sat
    if (dow === 0 || dow === 6) continue; // 跳过周末

    // 从 10:30 到 21:00，每 30 分钟一档
    for (let t = 10 * 60 + 30; t + durationMin <= 21 * 60; t += 30) {
      const hh = String(Math.floor(t / 60)).padStart(2, '0');
      const mm = String(t % 60).padStart(2, '0');
      const slotStart = new Date(`${dateStr}T${hh}:${mm}:00+08:00`);
      const slotEnd   = new Date(slotStart.getTime() + durationMin * 60 * 1000);

      // 跳过已过去的时段
      if (slotStart <= now) continue;

      // 检查冲突
      const conflict = busyTimes.some(b => slotStart < b.end && slotEnd > b.start);
      if (!conflict) {
        freeSlots.push({ start: slotStart.toISOString(), end: slotEnd.toISOString() });
      }
    }
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

      // 查日程（用正确的北京时间格式）
      const now = new Date();
      const toBeijingISO = (d) => {
        const bj = new Date(d.getTime() + 8 * 3600 * 1000);
        return bj.toISOString().replace('Z', '+08:00').replace(/\.\d+/, '');
      };
      const beginTime = toBeijingISO(now);
      const endDate = new Date(now);
      endDate.setDate(endDate.getDate() + days);
      const endTime = toBeijingISO(endDate);

      const data = querySchedules(user.userId, beginTime, endTime);
      const schedules = (data?.events || []).map(e => ({
        startTime: e.start + '+08:00',
        endTime:   e.end   + '+08:00'
      }));

      // 计算空闲
      const freeSlots = calcFreeSlots(schedules, days, duration);

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
