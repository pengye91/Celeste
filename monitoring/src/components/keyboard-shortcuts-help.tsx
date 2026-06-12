"use client";

import * as Dialog from "@radix-ui/react-dialog";
import X from "lucide-react/dist/esm/icons/x";
import { SHORTCUTS, comboToReadable, type ShortcutContext } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

const CONTEXT_LABELS: Record<ShortcutContext, string> = {
  global: "Global",
  workflow: "Workflow page",
  "workflows-list": "Workflows list",
};

/**
 * Modal dialog listing every keyboard shortcut. Radix Dialog handles
 * `Esc` to close; clicking the overlay also closes.
 */
export function KeyboardShortcutsHelp({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const grouped: Record<ShortcutContext, typeof SHORTCUTS[number][]> = {
    global: [],
    workflow: [],
    "workflows-list": [],
  };
  for (const s of SHORTCUTS) grouped[s.context].push(s);

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay
          className="fixed inset-0 z-[60] bg-space-950/70 backdrop-blur-sm"
          data-testid="kshortcut-overlay"
        />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[70]",
            "w-[min(640px,90vw)] max-h-[80vh] overflow-auto",
            "rounded-md border border-space-500 bg-space-900/95 backdrop-blur-sm",
            "p-6 shadow-2xl"
          )}
          data-testid="kshortcut-dialog"
        >
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <Dialog.Title className="text-2xl font-display text-space-100">
                Keyboard Shortcuts
              </Dialog.Title>
              <Dialog.Description className="text-sm text-space-300 mt-1">
                Power-user keys for navigating the observatory.
              </Dialog.Description>
            </div>
            <Dialog.Close
              aria-label="Close keyboard shortcuts"
              className="text-space-300 hover:text-aurora-400 transition-colors p-1"
            >
              <X className="w-5 h-5" />
            </Dialog.Close>
          </div>

          <div className="flex flex-col gap-5">
            {(Object.keys(grouped) as ShortcutContext[]).map((ctx) => (
              <section key={ctx} data-testid={`kshortcut-group-${ctx}`}>
                <h3 className="text-xs uppercase tracking-widest text-space-400 mb-2">
                  {CONTEXT_LABELS[ctx]}
                </h3>
                <ul className="flex flex-col gap-1.5">
                  {grouped[ctx].map((s) => (
                    <li
                      key={s.id}
                      className="flex items-center justify-between gap-3 px-3 py-2 rounded-md bg-space-800/60 border border-space-500/30"
                    >
                      <span className="text-sm text-space-200">
                        {s.description}
                      </span>
                      <kbd
                        className="font-mono text-xs px-2 py-1 rounded bg-space-700 text-aurora-300 border border-space-500/40"
                        data-testid={`kshortcut-combo-${s.id}`}
                      >
                        {comboToReadable(s.combo)}
                      </kbd>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
