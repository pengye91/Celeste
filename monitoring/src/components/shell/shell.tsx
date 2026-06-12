"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/shell/top-bar";
import { SideRail } from "@/components/shell/side-rail";
import { MainStage } from "@/components/shell/main-stage";
import { KeyboardShortcutsHelp } from "@/components/keyboard-shortcuts-help";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";

/**
 * Top-level shell. Owns the keyboard shortcuts dialog state and
 * registers the global shortcuts so they are active on every page.
 */
export function Shell({ children }: { children: React.ReactNode }) {
  const [helpOpen, setHelpOpen] = useState(false);
  const openHelp = useCallback(() => setHelpOpen(true), []);
  const closeHelp = useCallback(() => setHelpOpen(false), []);
  const router = useRouter();

  useKeyboardShortcuts({
    "Ctrl+Shift+D": () => router.push("/"),
    "Ctrl+Shift+W": () => router.push("/workflows"),
    "Ctrl+Shift+O": () => router.push("/observatory"),
    "Ctrl+Shift+A": () => router.push("/agents"),
    "Ctrl+K": () => {
      const el = document.querySelector<HTMLElement>("[data-search-input]");
      el?.focus();
    },
    "Ctrl+/": openHelp,
    Esc: closeHelp,
  });

  return (
    <div className="flex flex-col h-screen bg-space-void">
      <TopBar onOpenHelp={openHelp} />
      <div className="flex flex-1 min-h-0">
        <SideRail />
        <MainStage>{children}</MainStage>
      </div>
      <KeyboardShortcutsHelp open={helpOpen} onClose={closeHelp} />
    </div>
  );
}
