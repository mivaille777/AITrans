import { describe, expect, it } from "vitest"

import { formatConversationTime, formatConversationTimestamp } from "./conversation-time"

describe("conversation time", () => {
  const now = new Date(2026, 9, 6, 0, 5)

  it.each([
    [new Date(2026, 9, 6, 0, 1), "00:01"],
    [new Date(2026, 9, 5, 23, 59), "昨天"],
    [new Date(2026, 9, 4, 23, 59), "前天"],
    [new Date(2026, 9, 3), "3天前"],
    [new Date(2026, 8, 30), "6天前"],
    [new Date(2026, 8, 29), "一周前"],
    [new Date(2026, 8, 26), "一周前"],
    [new Date(2026, 8, 22), "两周前"],
    [new Date(2026, 8, 7), "4周前"],
    [new Date(2026, 8, 6), "一个月前"],
    [new Date(2026, 7, 6), "两个月前"],
    [new Date(2026, 6, 6), "3个月前"],
    [new Date(2025, 9, 7), "11个月前"],
    [new Date(2025, 9, 6), "一年前"],
    [new Date(2024, 9, 6), "两年前"],
    [new Date(2023, 9, 6), "3年前"],
  ])("formats %s as %s using local calendar dates", (date, expected) => {
    expect(formatConversationTime(date.toISOString(), now)).toBe(expected)
  })

  it("counts complete months and years across short months and leap years", () => {
    expect(formatConversationTime(new Date(2026, 0, 31).toISOString(), new Date(2026, 1, 27))).toBe("3周前")
    expect(formatConversationTime(new Date(2026, 0, 31).toISOString(), new Date(2026, 1, 28))).toBe("一个月前")
    expect(formatConversationTime(new Date(2024, 1, 29).toISOString(), new Date(2025, 1, 28))).toBe("一年前")
  })

  it("includes local date, seconds and timezone in the exact timestamp", () => {
    const value = new Date(2026, 9, 5, 21, 37, 8).toISOString()
    expect(formatConversationTimestamp(value)).toMatch(/^2026年10月5日 21:37:08 GMT(?:[+-]\d{2}:\d{2})?$/)
  })

  it("leaves missing or invalid timestamps empty", () => {
    for (const value of ["", "invalid-date"]) {
      expect(formatConversationTime(value, now)).toBe("")
      expect(formatConversationTimestamp(value)).toBe("")
    }
  })
})
