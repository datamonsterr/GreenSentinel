import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(resolve(__dirname, "../../..", p), "utf8");
const FILES = [
  "components/ai-elements/message.tsx",
  "components/copilot/analyst-copilot-panel.tsx",
  "components/adjudication/driver-relay-tab.tsx",
];
const PALETTE =
  /\b(?:bg|text|border|ring)-(?:emerald|green|red|rose|lime|teal|amber|orange|yellow|blue|indigo|violet|purple|sky|cyan|pink|fuchsia)-\d{2,3}\b/;

describe("chat cyan theme tokens", () => {
  it.each(FILES)("%s has no navy hex or palette classes", (f) => {
    const src = read(f);
    expect(src).not.toMatch(/#16273b/i);
    expect(src).not.toMatch(PALETTE);
  });

  it("user bubble uses cyan-soft with ink text and line border", () => {
    const src = read("components/ai-elements/message.tsx");
    expect(src).toContain("group-[.is-user]:bg-gs-cyan-soft");
    expect(src).toContain("group-[.is-user]:text-gs-ink-2");
    expect(src).not.toContain("is-user:dark");
  });

  it("assistant bubble is a white card with gs-line border", () => {
    const src = read("components/copilot/analyst-copilot-panel.tsx");
    expect(src).toMatch(/rounded-tl-md border border-gs-line bg-white/);
  });

  it("copilot timestamps use muted token and send button is primary", () => {
    const src = read("components/copilot/analyst-copilot-panel.tsx");
    expect(src).not.toMatch(/<time[^>]*text-slate-400/);
    expect(src).toMatch(/aria-label=\{vi \? "Gửi tin nhắn"[^]*?bg-primary text-white/);
  });

  it("relay: analyst bubble is cyan-soft and right-aligned, others white", () => {
    const src = read("components/adjudication/driver-relay-tab.tsx");
    expect(src).toContain("ml-auto bg-gs-cyan-soft border border-gs-cyan/30");
    expect(src).not.toMatch(/driver_agent"\s*\?\s*"bg-white[^]*?: "bg-white/);
  });

  it("driver app bubble keeps its own theme (no cyan border leak)", () => {
    const src = read("components/driver/chat/driver-chat-view.tsx");
    expect(src).toContain("group-[.is-user]:border-0");
  });

  it("copilot user bubble has no white text on cyan-soft", () => {
    const src = read("components/copilot/analyst-copilot-panel.tsx");
    expect(src).not.toMatch(/text-white !text-white/);
    expect(src).not.toMatch(/text-white\/70/);
  });
});
