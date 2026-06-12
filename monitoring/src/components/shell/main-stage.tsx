import { cn } from "@/lib/utils";

export interface MainStageProps {
  children: React.ReactNode;
  className?: string;
}

export function MainStage({ children, className }: MainStageProps) {
  return (
    <div className="relative flex flex-1 min-h-0">
      {/* Aurora backdrop */}
      <div className="aurora-bg" aria-hidden="true" />

      {/* Grain overlay */}
      <div className="grain-overlay" aria-hidden="true" />

      {/* Content */}
      <main
        id="main-content"
        // The cmc-main alias is preserved so the legacy useSkipLink()
        // utility in src/lib/a11y.ts still focuses this element when
        // any consumer wires it up.
        data-cmc-main
        tabIndex={-1}
        className={cn(
          "relative z-10 flex-1 overflow-auto p-4 lg:p-6 outline-none",
          className
        )}
      >
        {children}
      </main>
    </div>
  );
}
