import { describe, expect, it } from "vitest"

import {
  defaultKnowledgeAccessPolicy,
  normalizeKnowledgeAccessPolicy,
  serializeKnowledgeAccessPolicy,
} from "./knowledge-access-policy"

describe("knowledge access policy", () => {
  it("defaults to auto", () => {
    expect(defaultKnowledgeAccessPolicy).toBe("auto")
    expect(normalizeKnowledgeAccessPolicy(undefined)).toBe("auto")
  })

  it("accepts the three supported modes", () => {
    expect(serializeKnowledgeAccessPolicy("always")).toBe("always")
    expect(serializeKnowledgeAccessPolicy("never")).toBe("never")
    expect(serializeKnowledgeAccessPolicy("auto")).toBe("auto")
  })

  it("normalizes invalid values to auto", () => {
    expect(normalizeKnowledgeAccessPolicy("on")).toBe("auto")
    expect(normalizeKnowledgeAccessPolicy(null)).toBe("auto")
  })
})
