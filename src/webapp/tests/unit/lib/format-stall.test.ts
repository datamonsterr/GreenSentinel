import { describe, expect, it } from "vitest";
import { formatStallDuration } from "@/lib/utils";

describe("formatStallDuration", () => {
  it("renders missing SSD as insufficient data, never as 0", () => {
    expect(formatStallDuration(null)).toBe("Không đủ dữ liệu");
    expect(formatStallDuration(undefined)).toBe("Không đủ dữ liệu");
  });

  it("renders a measured zero and positive durations in seconds", () => {
    expect(formatStallDuration(0)).toBe("0s");
    expect(formatStallDuration(210)).toBe("210s");
  });
});
