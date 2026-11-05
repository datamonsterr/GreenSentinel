import { afterEach, expect, it, vi } from "vitest";
import { observeTestRun } from "@/lib/test-run-stream";

afterEach(() => vi.unstubAllGlobals());

function stream(data: string) {
  return new Response(new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode(data));
    controller.close();
  } }));
}

it("reconciles a gap, resumes at the last ID, and ignores replayed events", async () => {
  const first = { event_id: "one", event_type: "step.progress", step_index: 1 };
  const last = { event_id: "two", event_type: "run.completed", step_index: 2 };
  const fetcher = vi.fn()
    .mockResolvedValueOnce(stream(`id: one\ndata: ${JSON.stringify(first)}\n\n`))
    .mockResolvedValueOnce(Response.json({ status: "RUNNING" }))
    .mockResolvedValueOnce(Response.json([]))
    .mockResolvedValueOnce(stream(`data: ${JSON.stringify(first)}\n\ndata: ${JSON.stringify(last)}\n\n`));
  vi.stubGlobal("fetch", fetcher);
  const onEvent = vi.fn();
  const onReconcile = vi.fn();
  const connection = vi.fn();
  await observeTestRun("run-1", new AbortController().signal, { onEvent, onReconcile, onConnection: connection });
  expect(onEvent.mock.calls.map(([event]) => event.event_id)).toEqual(["one", "two"]);
  expect(onReconcile).toHaveBeenCalledWith({ status: "RUNNING" }, []);
  expect(fetcher.mock.calls[3][0]).toContain("last_event_id=one");
  expect(connection).toHaveBeenCalledWith("reconnecting");
});

it("uses persisted terminal state after disconnect without opening another stream", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(stream(""))
    .mockResolvedValueOnce(Response.json({ status: "COMPLETED", current_step: 8, total_steps: 8 }))
    .mockResolvedValueOnce(Response.json([]));
  vi.stubGlobal("fetch", fetcher);
  const onReconcile = vi.fn();
  await observeTestRun("run-1", new AbortController().signal, { onEvent: vi.fn(), onReconcile, onConnection: vi.fn() });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(onReconcile).toHaveBeenCalledWith(expect.objectContaining({ status: "COMPLETED" }), []);
});

it("does not append a sample again when REST reconciliation already includes its step", async () => {
  const first = { event_id: "a", event_type: "step.progress", step_index: 1, sample: { step_index: 1 } };
  const replay = { event_id: "b", event_type: "step.progress", step_index: 2, sample: { step_index: 2 } };
  const last = { event_id: "c", event_type: "run.completed", step_index: 3 };
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(stream(`data: ${JSON.stringify(first)}\n\n`))
    .mockResolvedValueOnce(Response.json({ status: "RUNNING", current_step: 2, total_steps: 3 }))
    .mockResolvedValueOnce(Response.json([{ step_index: 1 }, { step_index: 2 }]))
    .mockResolvedValueOnce(stream(`data: ${JSON.stringify(replay)}\n\ndata: ${JSON.stringify(last)}\n\n`)));
  const onEvent = vi.fn();
  await observeTestRun("run-1", new AbortController().signal, { onEvent, onReconcile: vi.fn(), onConnection: vi.fn() });
  expect(onEvent.mock.calls.map(([event]) => event.event_id)).toEqual(["a", "c"]);
});
