import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";

describe("useCopyToClipboard", () => {
  let writeText: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    (window as unknown as Record<string, unknown>).__toasterAdd = vi.fn(
      () => "toast-id"
    );
  });

  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).__toasterAdd;
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
  });

  it("copies text and fires a success toast", async () => {
    const { result } = renderHook(() => useCopyToClipboard());
    let success = false;
    await act(async () => {
      success = await result.current.copy("hello", "workflow id");
    });
    expect(success).toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
    const add = (window as unknown as Record<string, unknown>).__toasterAdd as ReturnType<
      typeof vi.fn
    >;
    expect(add).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Copied workflow id", variant: "success" })
    );
  });

  it("uses a generic success message when no label is provided", async () => {
    const { result } = renderHook(() => useCopyToClipboard());
    await act(async () => {
      await result.current.copy("hello");
    });
    const add = (window as unknown as Record<string, unknown>).__toasterAdd as ReturnType<
      typeof vi.fn
    >;
    expect(add).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Copied" })
    );
  });

  it("returns false and toasts error when clipboard write rejects", async () => {
    writeText.mockRejectedValueOnce(new Error("denied"));
    const { result } = renderHook(() => useCopyToClipboard());
    let success = true;
    await act(async () => {
      success = await result.current.copy("hello", "id");
    });
    expect(success).toBe(false);
    const add = (window as unknown as Record<string, unknown>).__toasterAdd as ReturnType<
      typeof vi.fn
    >;
    expect(add).toHaveBeenCalledWith(
      expect.objectContaining({ variant: "error" })
    );
  });

  it("returns false and does not throw when clipboard is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    const { result } = renderHook(() => useCopyToClipboard());
    let success = true;
    await act(async () => {
      success = await result.current.copy("hello");
    });
    expect(success).toBe(false);
    const add = (window as unknown as Record<string, unknown>).__toasterAdd as ReturnType<
      typeof vi.fn
    >;
    expect(add).not.toHaveBeenCalled();
  });
});
