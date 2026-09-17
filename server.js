require('dotenv').config();
const express = require('express');
const http = require('http');
const path = require('path');
const WebSocket = require('ws');
const { Server } = require('socket.io');
const { WebcastPushConnection } = require('tiktok-live-connector');

// --- Tích hợp các Module mới ---
require('./telegram'); // Khởi chạy Telegram Bot ngầm
const { runBrowserTask } = require('./scraper');

const app = express();
const server = http.createServer(app);

const PORT = process.env.PORT || 3000;
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || '';

// --- WebSocket Dual-Engine Setup ---
// Native WebSocket Server cho Slave/Bot Hub (đường dẫn /ws)
const wss = new WebSocket.Server({ noServer: true });

// Socket.IO Server cho Control Panel Interface (đường dẫn /socket.io)
const io = new Server(server, { cors: { origin: '*' }, pingInterval: 5000, pingTimeout: 2000 });

// Phân luồng HTTP Upgrade request giữa WS và Socket.IO
server.on('upgrade', (request, socket, head) => {
    const pathname = new URL(request.url, `http://${request.headers.host}`).pathname;
    if (pathname === '/socket.io/') {
        // Socket.IO tự xử lý upgrade
        return;
    }
    wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
    });
});

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.static(__dirname));

// ==========================================
// 💾 IN-MEMORY DATABASE & STATE STORAGE
// ==========================================
let users = [
    { id: 1, username: 'admin_hades', name: 'Hades Admin', role: 'SuperAdmin', status: 'Active' },
    { id: 2, username: 'hendy_op', name: 'Hendy Operator', role: 'Operator', status: 'Active' },
    { id: 3, username: 'viewer_01', name: 'Guest Viewer', role: 'Viewer', status: 'Inactive' }
];

const activeSlaves = new Map();
const activeBots = new Map();
const activeLiveMonitors = new Map();

// Global Broadcast helper (cho cả Native WS lẫn Socket.IO)
function broadcastToAll(data) {
    const payload = typeof data === 'string' ? data : JSON.stringify(data);
    
    // Broadcast tới tất cả client Native WebSocket
    wss.clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
            client.send(payload);
        }
    });

    // Broadcast tới tất cả client Socket.IO (Dashboard UI)
    io.emit('system_broadcast', typeof data === 'string' ? JSON.parse(data) : data);
}

// ==========================================
// 🛡️ MIDDLEWARE: RBAC AUTHORIZATION
// ==========================================
const authorize = (allowedRoles) => {
    return (req, res, next) => {
        const userRole = req.headers['x-user-role'] || 'Viewer';
        if (!allowedRoles.includes(userRole)) {
            return res.status(403).json({ success: false, message: 'Quyền truy cập bị từ chối (403 Forbidden)' });
        }
        next();
    };
};

// ==========================================
// 👤 REST API: QUẢN LÝ NGƯỜI DÙNG (CRUD)
// ==========================================
app.get('/api/v1/users', authorize(['SuperAdmin', 'Operator', 'Viewer']), (req, res) => {
    res.json({ success: true, data: users });
});

app.post('/api/v1/users', authorize(['SuperAdmin']), (req, res) => {
    const { username, name, role } = req.body;
    if (!username || !role) return res.status(400).json({ success: false, message: 'Thiếu thông tin người dùng' });
    const newUser = { id: Date.now(), username, name: name || username, role, status: 'Active' };
    users.push(newUser);
    io.emit('user_updated', { action: 'CREATE', user: newUser });
    res.status(201).json({ success: true, data: newUser });
});

app.put('/api/v1/users/:id', authorize(['SuperAdmin']), (req, res) => {
    const { id } = req.params;
    const { name, role, status } = req.body;
    const index = users.findIndex(u => u.id == id);
    if (index === -1) return res.status(404).json({ success: false, message: 'Không tìm thấy người dùng' });

    users[index] = { 
        ...users[index], 
        name: name || users[index].name, 
        role: role || users[index].role, 
        status: status || users[index].status 
    };
    io.emit('user_updated', { action: 'UPDATE', user: users[index] });
    res.json({ success: true, data: users[index] });
});

app.delete('/api/v1/users/:id', authorize(['SuperAdmin']), (req, res) => {
    const { id } = req.params;
    users = users.filter(u => u.id != id);
    io.emit('user_updated', { action: 'DELETE', id: Number(id) });
    res.json({ success: true, message: 'Xóa người dùng thành công' });
});

// ==========================================
// 📊 REST API: HỆ THỐNG & MONITORING
// ==========================================
app.get('/api/v1/system/status', (req, res) => {
    res.json({
        success: true,
        data: {
            system: 'Master Control Panel - Hendy & Hades V6100 Pro',
            uptime: Math.floor(process.uptime()),
            activeBots: activeBots.size,
            activeSlaves: activeSlaves.size,
            activeLiveSessions: activeLiveMonitors.size,
            totalUsers: users.length
        }
    });
});

app.get('/api/slaves', (req, res) => {
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    const slavesList = [];
    activeSlaves.forEach((client) => {
        slavesList.push({
            id: client.id,
            name: client.name,
            role: client.role,
            isOnLive: client.isOnLive,
            url: client.url,
            lastSeen: new Date(client.lastSeen).toLocaleTimeString('vi-VN')
        });
    });
    res.send(JSON.stringify(slavesList, null, 2));
});

app.get('/api/bots', (req, res) => {
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.send(JSON.stringify(Array.from(activeBots.values()), null, 2));
});

app.get('/send-command', (req, res) => {
    const cmd = req.query.cmd || 'ĐIỂM DANH + SC88 +';
    let count = 0;
    wss.clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
            client.send(JSON.stringify({ action: `CHAT|${cmd}` }));
            count++;
        }
    });
    res.send(`🚀 Đã phát lệnh thành công cho ${count} thiết bị: [ ${cmd} ]`);
});

// Endpoint kích hoạt Puppeteer thủ công
app.post('/api/run-scraper', async (req, res) => {
    const result = await runBrowserTask();
    res.json(result);
});

// ==========================================
// 🤖 AI MANAGER ENGINE
// ==========================================
async function processAiManagerCommand(userPrompt, systemContext) {
    if (GEMINI_API_KEY) {
        try {
            const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${GEMINI_API_KEY}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    contents: [{
                        parts: [{
                            text: `Bạn là AI Quản Lý Hệ Thống Hendy & Hades V6100 Pro. 
Trạng thái hệ thống hiện tại: 
- Số lượng Bot active: ${systemContext.botCount || 0}
- Số lượng Slave connected: ${systemContext.slaveCount || 0}
- Số phiên Live đang mở: ${systemContext.liveCount || 0}

Người dùng gửi câu lệnh: "${userPrompt}"

Hãy phân tích lệnh và trả về DUY NHẤT một chuỗi JSON theo định dạng chuẩn sau:
{
  "action": "START_ALL_BOTS" | "STOP_ALL_BOTS" | "ADD_BOT" | "EXPORT_CSV" | "CLEAR_LOGS" | "LOCK_USER" | "SYSTEM_STATUS" | "START_LIVE_BOOST" | "STOP_LIVE_BOOST" | "UNKNOWN",
  "reply": "Lời phản hồi ngắn gọn, chuyên nghiệp bằng tiếng Việt",
  "params": { "count": 1, "target": "" }
}`
                        }]
                    }]
                })
            });

            const data = await response.json();
            const textResponse = data.candidates?.[0]?.content?.parts?.[0]?.text;
            if (textResponse) {
                const cleanedJson = textResponse.replace(/```json|```/g, '').trim();
                return JSON.parse(cleanedJson);
            }
        } catch (err) {
            console.error('[AI GEMINI ERROR]:', err);
        }
    }

    let action = 'UNKNOWN';
    let reply = '🤖 AI Quản lý chưa hiểu rõ yêu cầu.';
    let params = {};

    if (userPrompt.toLowerCase().includes('chạy') || userPrompt.toLowerCase().includes('start')) {
        action = 'START_ALL_BOTS';
        reply = '🚀 AI Manager đã phát lệnh kích hoạt TẤT CẢ các Bot!';
    } else if (userPrompt.toLowerCase().includes('dừng') || userPrompt.toLowerCase().includes('stop')) {
        action = 'STOP_ALL_BOTS';
        reply = '⏹ AI Manager đã tạm dừng tất cả các Bot!';
    }

    return { action, reply, params };
}

app.post('/api/ai/manage', async (req, res) => {
    try {
        const { prompt, context } = req.body;
        if (!prompt) return res.status(400).json({ error: 'Vui lòng cung cấp câu lệnh' });

        const systemContext = {
            slaveCount: activeSlaves.size,
            botCount: activeBots.size,
            liveCount: activeLiveMonitors.size,
            ...(context || {})
        };

        const result = await processAiManagerCommand(prompt, systemContext);
        broadcastToAll({ type: 'AI_MANAGER_ACTION', action: result.action, params: result.params });
        res.json({ success: true, data: result });
    } catch (error) {
        console.error('[AI API ERROR]:', error);
        res.status(500).json({ error: 'Lỗi xử lý AI Manager' });
    }
});

// ==========================================
// 🔴 LIVE STREAM & TIKTOK CONNECTOR ENGINE
// ==========================================
app.post('/api/live/start-boost', (req, res) => {
    try {
        const { platform, targetUrl, username, targetViewers } = req.body;
        if (!platform || (!targetUrl && !username)) {
            return res.status(400).json({ success: false, error: 'Thiếu thông tin nền tảng hoặc Username phòng live' });
        }

        const sessionId = 'LIVE_' + Math.random().toString(36).substring(2, 8);
        const targetViewersCount = parseInt(targetViewers) || 500;

        if (platform.toLowerCase() === 'tiktok' && username) {
            const cleanUsername = username.replace('@', '').trim();
            const tiktokConnection = new WebcastPushConnection(cleanUsername);

            tiktokConnection.connect().then(state => {
                console.log(`[TIKTOK LIVE] Connected Room ID: ${state.roomId}`);
            }).catch(err => {
                console.error(`[TIKTOK ERROR]:`, err.message);
            });

            tiktokConnection.on('roomUser', data => {
                broadcastToAll({ type: 'LIVE_METRIC_UPDATE', sessionId, currentViewers: data.viewerCount });
            });

            activeLiveMonitors.set(sessionId, { sessionId, connection: tiktokConnection, platform: 'TikTok' });
        }

        res.json({ success: true, sessionId, message: `🚀 Đã khởi chạy Live Boost thành công!` });
    } catch (e) {
        res.status(500).json({ success: false, error: 'Lỗi server khi khởi chạy Live Boost' });
    }
});

// ==========================================
// 🔌 REALTIME ENGINE: NATIVE WEBSOCKET & SOCKET.IO
// ==========================================
wss.on('connection', (ws) => {
    ws.isAlive = true;
    console.log('[WS] Slave/Device client đã kết nối.');

    ws.on('pong', () => { ws.isAlive = true; });

    ws.on('message', (message) => {
        try {
            const data = JSON.parse(message);
            if (data.type === 'PING') {
                ws.send(JSON.stringify({ type: 'PONG', timestamp: data.timestamp }));
                return;
            }
        } catch (e) {
            console.error('[WS ERROR]:', e);
        }
    });
});

io.on('connection', (socket) => {
    console.log(`[Socket.IO] Admin Panel kết nối: ${socket.id}`);
    socket.on('latency_ping', (timestamp) => socket.emit('latency_pong', timestamp));
    socket.on('disconnect', () => console.log(`[Socket.IO] Ngắt kết nối: ${socket.id}`));
});

// Heartbeat kiểm tra kết nối đứt đối với Native WS
setInterval(() => {
    wss.clients.forEach((ws) => {
        if (ws.isAlive === false) return ws.terminate();
        ws.isAlive = false;
        ws.ping();
    });
}, 30000);

// ==========================================
// 🚀 SERVER INITIALIZATION
// ==========================================
server.listen(PORT, () => {
    console.log(`===================================================`);
    console.log(`🚀 MASTER CONTROL PANEL - HENDY & HADES V6100 PRO`);
    console.log(`📡 Server đang chạy trên port: ${PORT}`);
    console.log(`🔗 Web Dashboard: http://localhost:${PORT}`);
    console.log(`⚡ WebSocket Endpoint: ws://localhost:${PORT}/ws`);
    console.log(`===================================================`);
});
