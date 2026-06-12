"use client";

import Keyboard from "lucide-react/dist/esm/icons/keyboard";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Header button that opens the keyboard shortcuts help dialog. Rendered
 * in the top bar so users have a discoverable affordance alongside the
 * Ctrl+/ shortcut.
 */
export function KeyboardShortcutsHelpButton({
  onClick,
  className,
}: {
  onClick: () => void;
  className?: string;
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onClick}
      aria-label="Show keyboard shortcuts"
      title="Show keyboard shortcuts (Ctrl+/)"
      data-testid="kshortcut-help-button"
      className={cn("text-comet-400 hover:text-aurora-400", className)}
    >
      <Keyboard className="w-4 h-4" />
    </Button>
  );
}
