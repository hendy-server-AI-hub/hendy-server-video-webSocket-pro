import React, { useEffect, useState } from 'react';

export default function AdminApp() {
  const [serverStatus, setServerStatus] = useState<string>('Đang kiểm tra...');
  const [activeConnections, setActiveConnections] = useState<number>(0);

  useEffect(() => {
    // Giả lập gọi API lấy thống kê từ Cloudflare Worker hoặc Backend
    setTimeout(() => {
      setServerStatus('Hoạt động ổn định');
      setActiveConnections(12);
    }, 1000);
  }, []);

  return (
    <div style={{ fontFamily: 'Arial, sans-serif', padding: '24px', maxWidth: '800px', margin: '0 auto' }}>
      <h1>Hendy Admin Dashboard</h1>
      <p>Trang quản trị hệ thống video và WebSocket Vietsub.</p>
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginTop: '24px' }}>
        <div style={{ padding: '16px', border: '1px solid #ddd', borderRadius: '8px', background: '#f9f9f9' }}>
          <h3>Trạng thái Server</h3>
          <p style={{ color: 'green', fontWeight: 'bold' }}>{serverStatus}</p>
        </div>
        <div style={{ padding: '16px', border: '1px solid #ddd', borderRadius: '8px', background: '#f9f9f9' }}>
          <h3>Client WebSocket Đang Kết Nối</h3>
          <p style={{ fontSize: '24px', fontWeight: 'bold' }}>{activeConnections}</p>
        </div>
      </div>
    </div>
  );
}
