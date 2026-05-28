"use client";
import { useEffect, useRef, useState } from "react";
import type { TrajectoryEvent } from "./api";

export function useLiveRun(runId: string | null) {
  const [events, setEvents] = useState<TrajectoryEvent[]>([]);
  const [status, setStatus] = useState<"idle" | "connecting" | "open" | "closed" | "error">("idle");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!runId) return;
    const base = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8800";
    const wsUrl = base.replace(/^http/, "ws") + `/ws/runs/${runId}`;
    setStatus("connecting");
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    ws.onopen = () => setStatus("open");
    ws.onmessage = (msg) => {
      try {
        setEvents((prev) => [...prev, JSON.parse(msg.data) as TrajectoryEvent]);
      } catch {
        /* ignore malformed */
      }
    };
    ws.onerror = () => setStatus("error");
    ws.onclose = () => setStatus("closed");
    return () => {
      ws.close();
    };
  }, [runId]);

  return { events, status };
}
