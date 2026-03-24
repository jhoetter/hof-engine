import { describe, expect, it } from "vitest";
import { formatDurationMs } from "./thinkingDuration";

describe("formatDurationMs", () => {
  it("formats sub-minute", () => {
    expect(formatDurationMs(0)).toBe("0 seconds");
    expect(formatDurationMs(999)).toBe("0 seconds");
    expect(formatDurationMs(1000)).toBe("1 second");
    expect(formatDurationMs(2000)).toBe("2 seconds");
    expect(formatDurationMs(59_000)).toBe("59 seconds");
  });

  it("formats minutes", () => {
    expect(formatDurationMs(60_000)).toBe("1 minute");
    expect(formatDurationMs(125_000)).toBe("2 minutes 5 seconds");
    expect(formatDurationMs(3_540_000)).toBe("59 minutes");
  });

  it("formats hours with optional minutes and seconds", () => {
    expect(formatDurationMs(3_600_000)).toBe("1 hour");
    expect(formatDurationMs(3_660_000)).toBe("1 hour 1 minute");
    expect(formatDurationMs(3_661_000)).toBe("1 hour 1 minute 1 second");
    expect(formatDurationMs(7_320_000)).toBe("2 hours 2 minutes");
  });

  it("never goes negative", () => {
    expect(formatDurationMs(-500)).toBe("0 seconds");
  });
});
