// Kết nối tới WebSocket server
const ws = new WebSocket('ws://localhost:8000/ws/vietsub');

ws.onopen = function() {
    console.log('Đã kết nối thành công tới Vietsub Realtime Server');
    
    // Gửi một gói tin mẫu lên server
    const samplePayload = {
        text: "Hello everyone, welcome to the realtime translation stream."
    };
    ws.send(JSON.stringify(samplePayload));
};

ws.onmessage = function(event) {
    const response = JSON.parse(event.data);
    console.log('Nhận kết quả Vietsub từ Server:', response);
};

ws.onclose = function() {
    console.log('Đã ngắt kết nối khỏi WebSocket server');
};

ws.onerror = function(error) {
    console.error('Lỗi kết nối WebSocket:', error);
};
