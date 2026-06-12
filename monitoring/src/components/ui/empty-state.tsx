import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/**
 * Shared empty-state surface.
 *
 * Centralises the "illustrated Panel with reason + action" pattern used
 * across the dashboard, workflows list, and detail pages. The icon is
 * optional — a 120x120 line-art illustration from the existing
 * `empty-observatory-illustration` or `empty-agents-illustration` slots
 * in directly.
 *
 * Voice: the design system pairs a one-line reason with a one-line
 * action hint. We preserve that here.
 */
export interface EmptyStateAction {
  label: string;
  onClick?: () => void;
  href?: string;
}

export interface EmptyStateProps {
  /**
   * Optional illustration node. Pass one of the existing illustration
   * components (e.g. `EmptyObservatoryIllustration`) or any other 120x120
   * SVG. The illustration is centered and sized down on small viewports.
   */
  icon?: React.ReactNode;
  /** Primary headline — one line, sentence case. */
  title: string;
  /** Supporting reason — one line, sentence case. */
  description?: string;
  /** Optional primary call to action rendered as a Button. */
  action?: EmptyStateAction;
  /** Tighter vertical padding for use inside larger surfaces. */
  compact?: boolean;
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  compact = false,
  className,
}: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-col items-center text-center",
        compact ? "py-8" : "py-12",
        className
      )}
    >
      {icon ? (
        <div className="mb-4 opacity-90 motion-safe:animate-fade-in">
          {icon}
        </div>
      ) : null}
      <p className="text-lg font-display text-comet-300 mb-1">{title}</p>
      {description ? (
        <p className="text-sm text-comet-500 max-w-md">{description}</p>
      ) : null}
      {action ? (
        <div className="mt-5">
          {action.href ? (
            <Button asChild variant="primary" size="default">
              <a href={action.href}>{action.label}</a>
            </Button>
          ) : (
            <Button variant="primary" size="default" onClick={action.onClick}>
              {action.label}
            </Button>
          )}
        </div>
      ) : null}
    </div>
  );
}

export { EmptyState as default };
