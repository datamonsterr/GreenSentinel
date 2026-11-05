import {
  fetchPresetBatchRunDetail,
  streamTest,
  type PresetBatchEvent,
  type PresetBatchRunDetailResponse,
} from "./testApiClient";

export interface PresetBatchObserver {
  onEvent: (event: PresetBatchEvent) => void;
  onReconcile?: (batch: PresetBatchRunDetailResponse) => void;
  onConnection?: (state: "connected" | "reconnecting" | "closed") => void;
}

const TERMINAL_STATUSES = new Set(["COMPLETED", "CANCELLED", "FAILED"]);

/**
 * Resilient SSE observer for preset batch runs.
 * Subscribes to /presets/runs/{batch_id}/events and reconnects on drops with last_event_id.
 */
export async function observePresetBatchRun(
  batchId: string,
  signal: AbortSignal,
  observer: PresetBatchObserver
): Promise<void> {
  const seen = new Set<string>();
  let cursor: string | undefined;
  let finished = false;

  for (let attempt = 0; attempt < 5 && !signal.aborted; attempt++) {
    try {
      const qs = cursor ? `?last_event_id=${encodeURIComponent(cursor)}` : "";
      const response = await streamTest(`/presets/runs/${encodeURIComponent(batchId)}/events${qs}`, signal);
      if (signal.aborted) return;

      observer.onConnection?.("connected");
      const reader = response.body?.getReader();
      if (!reader) throw new Error("SSE stream body unavailable");

      const decoder = new TextDecoder();
      let buffer = "";
      let frameId: string | undefined;
      let eventType: string | undefined;
      const dataLines: string[] = [];

      const dispatch = () => {
        if (!dataLines.length || signal.aborted) return;
        const rawJson = dataLines.join("\n");
        let parsed: PresetBatchEvent;
        try {
          parsed = JSON.parse(rawJson) as PresetBatchEvent;
        } catch {
          return;
        }

        const effectiveType = eventType || parsed.event_type;
        if (!effectiveType || effectiveType === "connect") return;

        parsed.event_type = effectiveType;
        const identity = parsed.event_id || frameId;
        if (identity) {
          if (seen.has(identity)) return;
          seen.add(identity);
          cursor = identity;
        }

        observer.onEvent(parsed);
        if (effectiveType === "batch.completed" || effectiveType === "batch.cancelled") {
          finished = true;
        }
      };

      try {
        while (!signal.aborted && !finished) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split(/\r?\n/);
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (line.startsWith("id:")) {
              frameId = line.slice(3).trim();
            } else if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).trimStart());
            } else if (line === "") {
              dispatch();
              dataLines.length = 0;
              frameId = undefined;
              eventType = undefined;
            }
            if (finished || signal.aborted) break;
          }
        }
        if (dataLines.length && !finished) {
          dispatch();
        }
      } finally {
        await reader.cancel().catch(() => undefined);
      }

      if (finished || signal.aborted) {
        observer.onConnection?.("closed");
        return;
      }
    } catch {
      if (signal.aborted) return;
    }

    if (signal.aborted) return;
    observer.onConnection?.("reconnecting");

    // Reconcile batch state via REST
    try {
      const detail = await fetchPresetBatchRunDetail(batchId);
      if (signal.aborted) return;
      observer.onReconcile?.(detail);
      if (TERMINAL_STATUSES.has(detail.status)) {
        observer.onConnection?.("closed");
        return;
      }
    } catch {
      // Continue retrying stream
    }

    if (attempt >= 4) {
      observer.onConnection?.("closed");
      return;
    }

    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        signal.removeEventListener("abort", onAbort);
        resolve();
      }, 300 * 2 ** attempt);
      const onAbort = () => {
        clearTimeout(timer);
        resolve();
      };
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }
}
