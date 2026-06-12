import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const replaceMock = vi.fn();
const getMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => ({
    get: (k: string) => getMock(k),
    toString: () => "",
  }),
}));

import { useUrlState } from "@/hooks/useUrlState";

describe("useUrlState", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    getMock.mockReset();
  });

  it("returns defaultValue when no param is present", () => {
    getMock.mockReturnValue(null);
    const { result } = renderHook(() => useUrlState("status", "all"));
    expect(result.current[0]).toBe("all");
  });

  it("returns the value from the URL when present", () => {
    getMock.mockReturnValue("running");
    const { result } = renderHook(() => useUrlState("status", "all"));
    expect(result.current[0]).toBe("running");
  });

  it("falls back to defaultValue when the value is not in the allow list", () => {
    getMock.mockReturnValue("garbage");
    const { result } = renderHook(() =>
      useUrlState("status", "all", ["running", "paused"] as const)
    );
    expect(result.current[0]).toBe("all");
  });

  it("keeps the value when it is in the allow list", () => {
    getMock.mockReturnValue("paused");
    const { result } = renderHook(() =>
      useUrlState("status", "all", ["running", "paused"] as const)
    );
    expect(result.current[0]).toBe("paused");
  });

  it("calls router.replace with the new value", () => {
    getMock.mockReturnValue(null);
    const { result } = renderHook(() => useUrlState("status", "all"));
    act(() => result.current[1]("running"));
    expect(replaceMock).toHaveBeenCalledTimes(1);
    const [url, options] = replaceMock.mock.calls[0];
    expect(url).toContain("status=running");
    expect(options).toEqual({ scroll: false });
  });

  it("removes the param when set to the default value", () => {
    getMock.mockReturnValue(null);
    const { result } = renderHook(() => useUrlState("status", "all"));
    act(() => result.current[1]("all"));
    const [url] = replaceMock.mock.calls[0];
    expect(url).not.toContain("status=");
  });
});
