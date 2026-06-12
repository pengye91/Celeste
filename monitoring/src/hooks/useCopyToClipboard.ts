"use client";

import { useCallback } from "react";
import { useToast } from "@/hooks/useToast";

/**
 * Returns a function that copies a string to the clipboard and surfaces
 * success/failure through the CMC toast.
 *
 * - On success: emits a `success` toast whose message is "Copied
 *   {label}" (or just "Copied" when no label is given).
 * - On failure: emits an `error` toast. Never throws.
 * - When `navigator.clipboard` is unavailable (e.g. insecure context),
 *   the returned `copy` resolves to `false` and does not toast.
 */
export function useCopyToClipboard() {
  const { toast } = useToast();

  const copy = useCallback(
    async (text: string, label?: string): Promise<boolean> => {
      if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
        return false;
      }
      try {
        await navigator.clipboard.writeText(text);
        toast({
          message: label ? `Copied ${label}` : "Copied",
          variant: "success",
        });
        return true;
      } catch {
        toast({
          message: label
            ? `Failed to copy ${label}`
            : "Failed to copy to clipboard",
          variant: "error",
        });
        return false;
      }
    },
    [toast]
  );

  return { copy };
}
