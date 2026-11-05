import { fetchTestRunStatus, fetchTestSamples, streamTest, type TestSample } from "./testApiClient";

export interface RunStreamEvent {
  event_id?: string;
  event_type: string;
  step_index: number;
  sample?: TestSample;
  cancellation_actor?: string | null;
  cancellation_reason?: string | null;
}

export interface RunSnapshot {
  status: string;
  current_step: number;
  total_steps: number;
}

interface Observer {
  onEvent: (event: RunStreamEvent) => void;
  onReconcile: (run: RunSnapshot, samples: TestSample[]) => void;
  onConnection: (state: "connected" | "reconnecting") => void;
}

const terminal = new Set(["COMPLETED", "CANCELLED", "FAILED"]);

/** One stream at a time; reconcile persisted state whenever the transport loses a gap. */
export async function observeTestRun(runId: string, signal: AbortSignal, observer: Observer): Promise<void> {
  const seen = new Set<string>();
  let cursor: string | undefined;
  let finished = false;
  let recordedStep = -1;
  for (let attempt = 0; attempt < 4 && !signal.aborted; attempt++) {
    try {
      const suffix = cursor ? `?last_event_id=${encodeURIComponent(cursor)}` : "";
      const response = await streamTest(`/runs/${encodeURIComponent(runId)}/stream${suffix}`, signal);
      if (signal.aborted) return;
      observer.onConnection("connected");
      const reader = response.body?.getReader();
      if (!reader) throw new Error("Test API stream unavailable");
      const decoder = new TextDecoder();
      let buffer = "";
      let frameId: string | undefined;
      let data: string[] = [];
      const dispatch = () => {
        if (!data.length || signal.aborted) return;
        let event: RunStreamEvent;
        try { event = JSON.parse(data.join("\n")) as RunStreamEvent; } catch { return; }
        if (!event.event_type) return;
        const identity = event.event_id || frameId;
        if (identity) {
          if (seen.has(identity)) return;
          seen.add(identity);
          cursor = identity;
        }
        if (event.event_type === "step.progress" && event.sample) {
          if (event.step_index <= recordedStep) return;
          recordedStep = event.step_index;
        }
        observer.onEvent(event);
        finished = ["run.completed", "run.cancelled", "run.failed"].includes(event.event_type);
      };
      try {
        while (!signal.aborted && !finished) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split(/\r?\n/);
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (line.startsWith("id:")) frameId = line.slice(3).trim();
            else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
            else if (line === "") { dispatch(); data = []; frameId = undefined; }
            if (finished || signal.aborted) break;
          }
        }
        if (data.length && !finished) dispatch();
      } finally {
        await reader.cancel().catch(() => undefined);
      }
      if (finished || signal.aborted) return;
    } catch (error) {
      if (signal.aborted) return;
      if (attempt === 3) throw error;
    }
    observer.onConnection("reconnecting");
    const run = await fetchTestRunStatus(runId);
    if (signal.aborted) return;
    const samples = await fetchTestSamples(runId, 2000);
    if (signal.aborted) return;
    observer.onReconcile(run, samples);
    for (const sample of samples) recordedStep = Math.max(recordedStep, sample.step_index);
    if (terminal.has(run.status)) return;
    if (attempt === 3) throw new Error("Stream disconnected. Retry to reconcile the recorded run.");
    await new Promise<void>((resolve) => {
      const done = () => { clearTimeout(timer); signal.removeEventListener("abort", done); resolve(); };
      const timer = setTimeout(done, 250 * 2 ** attempt);
      signal.addEventListener("abort", done, { once: true });
    });
  }
}
