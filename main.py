from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import logging

# Thiết lập logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Vietsub Realtime WebSocket Server",
    description="Backend xử lý WebSocket phụ đề thời gian thực cho hệ thống video",
    version="1.0.0"
)

# Cấu hình CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client đã kết nối. Tổng số kết nối: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client đã ngắt kết nối. Tổng số kết nối: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.get("/")
def health_check():
    return {"status": "running", "service": "vietsub-realtime-server"}

@app.websocket("/ws/vietsub")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Nhận dữ liệu text hoặc audio stream từ client (studio-web / client)
            data = await websocket.receive_text()
            logger.info(f"Nhận dữ liệu từ client: {data}")
            
            try:
                payload = json.loads(data)
                text_input = payload.get("text", "")
                
                # Xử lý giả lập dịch/tạo vietsub realtime (có thể tích hợp Whisper hoặc LLM tại đây)
                response_data = {
                    "status": "success",
                    "transcript": text_input,
                    "vietsub": f"[Vietsub Realtime]: {text_input}"
                }
                
                # Phản hồi lại kết quả qua WebSocket
                await websocket.send_text(json.dumps(response_data))
                
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "status": "error",
                    "message": "Dữ liệu không hợp lệ (yêu cầu định dạng JSON)"
                }))
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Kết nối WebSocket đã bị ngắt")
    except Exception as e:
        logger.error(f"Lỗi hệ thống WebSocket: {e}")
        manager.disconnect(websocket)
