/** Minimal browser example for apps/studio-web.
 * `wsUrl` must point to wss://.../ws/vietsub in production.
 */
export function connectVietsubRealtime({ wsUrl, onResult, onError, authToken }) {
  const socket = new WebSocket(wsUrl);

  socket.addEventListener("open", () => {
    if (authToken) {
      // Required only when the server has REQUIRE_WS_AUTH=true.
      socket.send(JSON.stringify({ type: "auth", token: authToken }));
    }
  });

  socket.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.status === "error") {
        onError?.(payload);
      } else {
        onResult?.(payload);
      }
    } catch {
      onError?.({ code: "invalid_server_response" });
    }
  });

  socket.addEventListener("error", () => {
    onError?.({ code: "websocket_error" });
  });

  return {
    socket,
    translate(text, { sourceLang = "auto", targetLang = "vi", requestId } = {}) {
      if (socket.readyState !== WebSocket.OPEN) throw new Error("WebSocket is not connected");
      socket.send(JSON.stringify({
        type: "translate_text",
        request_id: requestId ?? crypto.randomUUID(),
        text,
        source_lang: sourceLang,
        target_lang: targetLang,
      }));
    },
    async transcribeAudio(file, { sourceLang = "auto", targetLang = "vi", requestId } = {}) {
      if (socket.readyState !== WebSocket.OPEN) throw new Error("WebSocket is not connected");
      const audioBase64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const dataUrl = String(reader.result ?? "");
          resolve(dataUrl.slice(dataUrl.indexOf(",") + 1));
        };
        reader.onerror = () => reject(reader.error ?? new Error("Could not read audio file"));
        reader.readAsDataURL(file);
      });
      socket.send(JSON.stringify({
        type: "transcribe_audio",
        request_id: requestId ?? crypto.randomUUID(),
        filename: file.name,
        audio_base64: audioBase64,
        source_lang: sourceLang,
        target_lang: targetLang,
      }));
    },
    close() {
      socket.close(1000, "Client closed connection");
    },
  };
}
