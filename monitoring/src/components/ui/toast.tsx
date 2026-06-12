"use client";

import { cn } from "@/lib/utils";
import X from "lucide-react/dist/esm/icons/x";
import { useEffect, useState } from "react";

export interface Toast {
  id: string;
  message: string;
  variant?: "success" | "error" | "info" | "warning";
  duration?: number;
}

interface ToastItemProps {
  toast: Toast;
  onRemove: (id: string) => void;
}

const variantStyles = {
  success: "border-aurora-500/30 bg-aurora-500/10 text-aurora-400",
  error: "border-mars-500/30 bg-mars-500/10 text-mars-400",
  info: "border-nebula-500/30 bg-nebula-500/10 text-nebula-400",
  warning: "border-solar-500/30 bg-solar-500/10 text-solar-400",
};

function ToastItem({ toast, onRemove }: ToastItemProps) {
  const [isExiting, setIsExiting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsExiting(true);
      setTimeout(() => onRemove(toast.id), 300);
    }, toast.duration ?? 4000);
    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, onRemove]);

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-3 rounded-md border shadow-lg backdrop-blur-sm transition-all duration-300",
        isExiting ? "opacity-0 translate-x-4" : "opacity-100 translate-x-0",
        variantStyles[toast.variant ?? "info"]
      )}
      role="alert"
    >
      <span className="text-sm font-medium">{toast.message}</span>
      <button
        onClick={() => {
          setIsExiting(true);
          setTimeout(() => onRemove(toast.id), 300);
        }}
        className="ml-auto shrink-0 opacity-70 hover:opacity-100 transition-opacity"
        aria-label="Dismiss toast"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = (toast: Omit<Toast, "id">) => {
    const id = Math.random().toString(36).slice(2, 9);
    setToasts((prev) => [...prev, { ...toast, id }]);
    return id;
  };

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // Expose addToast globally for the hook
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__toasterAdd = addToast;
    return () => {
      delete (window as unknown as Record<string, unknown>).__toasterAdd;
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-80">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onRemove={removeToast} />
      ))}
    </div>
  );
}
