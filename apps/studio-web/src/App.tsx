import React, { useState, useEffect, useRef } from 'react';

export default function StudioApp() {
  const [subtitles, setSubtitles] = useState<string[]>([]);
  const [inputMessage, setInputMessage] = useState<string>('');
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Kết nối tới WebSocket Vietsub Server
    const ws = new WebSocket('ws://localhost:8000/ws/vietsub');
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('Studio đã kết nối WebSocket Vietsub');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.vietsub) {
        setSubtitles((prev) => [...prev, data.vietsub]);
      }
    };

    return () => {
      ws.close();
    };
  }, []);

  const handleSend = () => {
    if (wsRef.current && inputMessage.trim()) {
      wsRef.current.send(JSON.stringify({ text: inputMessage }));
      setInputMessage('');
    }
  };

  return (
    <div style={{ fontFamily: 'Arial, sans-serif', padding: '24px', maxWidth: '900px', margin: '0 auto' }}>
      <h1>Studio Biên Tập Vietsub Realtime</h1>
      
      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
        <input
          type="text"
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          placeholder="Nhập nội dung test phụ đề..."
          style={{ flex: 1, padding: '8px', fontSize: '16px' }}
        />
        <button onClick={handleSend} style={{ padding: '8px 16px', fontSize: '16px', cursor: 'pointer' }}>
          Gửi dữ liệu
        </button>
      </div>

      <div style={{ border: '1px solid #ccc', borderRadius: '8px', padding: '16px', height: '300px', overflowY: 'auto', background: '#1e1e1e', color: '#00ffcc' }}>
        <h3>Luồng Vietsub Thời Gian Thực:</h3>
        {subtitles.length === 0 ? (
          <p style={{ color: '#888' }}>Chưa có phụ đề nào...</p>
        ) : (
          subtitles.map((sub, index) => (
            <div key={index} style={{ margin: '8px 0' }}>
              {sub}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
