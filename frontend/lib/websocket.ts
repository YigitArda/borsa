"use client";

import { useState, useEffect, useRef, useCallback } from "react";

export type WebSocketStatus = "connecting" | "open" | "closed" | "error";

export interface WebSocketMessage {
  type: string;
  payload: unknown;
  timestamp?: string;
}

export function useWebSocket(url: string) {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<WebSocketStatus>("connecting");
  const [messages, setMessages] = useState<WebSocketMessage[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const send = useCallback((data: string | object) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      const payload = typeof data === "string" ? data : JSON.stringify(data);
      ws.send(payload);
      return true;
    }
    return false;
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  useEffect(() => {
    let isMounted = true;

    function connect() {
      if (!isMounted) return;
      setStatus("connecting");

      try {
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMounted) return;
          setConnected(true);
          setStatus("open");
        };

        ws.onmessage = (event) => {
          if (!isMounted) return;
          try {
            const parsed = JSON.parse(event.data) as WebSocketMessage;
            setMessages((prev) => [...prev, parsed]);
          } catch {
            // If not JSON, store as generic message
            setMessages((prev) => [
              ...prev,
              { type: "raw", payload: event.data, timestamp: new Date().toISOString() },
            ]);
          }
        };

        ws.onerror = () => {
          if (!isMounted) return;
          setConnected(false);
          setStatus("error");
        };

        ws.onclose = () => {
          if (!isMounted) return;
          setConnected(false);
          setStatus("closed");
          // Auto-reconnect after 3s
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, 3000);
        };
      } catch {
        if (!isMounted) return;
        setStatus("error");
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, 3000);
      }
    }

    connect();

    return () => {
      isMounted = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [url]);

  return { connected, messages, send, status, clearMessages };
}
