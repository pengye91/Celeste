"use client";

import { useState, useEffect } from "react";
import Search from "lucide-react/dist/esm/icons/search";
import { Input } from "@/components/ui/input";
import { StatusOrb } from "@/components/ui/status-orb";
import { KeyboardShortcutsHelpButton } from "@/components/keyboard-shortcuts-help-button";
import { cn } from "@/lib/utils";

export function TopBar({
  className,
  onOpenHelp,
}: {
  className?: string;
  onOpenHelp?: () => void;
}) {
  const [serverTime, setServerTime] = useState<string>("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setServerTime(
        now.toLocaleTimeString("en-US", {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header
      className={cn(
        "h-14 border-b border-space-500 bg-space-900/80 backdrop-blur-md flex items-center px-4 gap-4 sticky top-0 z-sticky",
        className
      )}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 shrink-0">
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="text-aurora-500"
        >
          <circle
            cx="12"
            cy="12"
            r="3"
            stroke="currentColor"
            strokeWidth="1.5"
            fill="none"
          />
          <ellipse
            cx="12"
            cy="12"
            rx="9"
            ry="4"
            stroke="currentColor"
            strokeWidth="1"
            fill="none"
            transform="rotate(30 12 12)"
          />
          <ellipse
            cx="12"
            cy="12"
            rx="9"
            ry="4"
            stroke="currentColor"
            strokeWidth="1"
            fill="none"
            transform="rotate(-30 12 12)"
          />
          <circle cx="12" cy="12" r="1" fill="currentColor" />
        </svg>
        <span className="font-display text-lg tracking-wide text-comet-100">
          Celeste
        </span>
      </div>

      {/* Search */}
      <div className="flex-1 max-w-md">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-comet-500" />
          <Input
            data-search-input
            placeholder="Search workflows, agents, events..."
            className="pl-9 bg-space-800 border-space-500 text-sm"
          />
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-4 shrink-0">
        {onOpenHelp && (
          <KeyboardShortcutsHelpButton onClick={onOpenHelp} />
        )}
        <div className="flex items-center gap-2 text-xs font-mono text-comet-400">
          <StatusOrb
            variant="success"
            size="sm"
          />
          <span className="hidden sm:inline">
            Connected
          </span>
        </div>
        <div className="text-xs font-mono text-comet-500 tabular-nums">
          {serverTime}
        </div>
      </div>
    </header>
  );
}
