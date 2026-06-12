"use client";

import { useCallback } from "react";

export interface ToastOptions {
  message: string;
  variant?: "success" | "error" | "info" | "warning";
  duration?: number;
}

export function useToast() {
  const toast = useCallback((options: ToastOptions) => {
    const add = (window as unknown as Record<string, unknown>).__toasterAdd as
      | ((opts: ToastOptions) => string)
      | undefined;
    if (add) {
      return add(options);
    }
    console.warn("Toaster not mounted");
    return "";
  }, []);

  return { toast };
}
