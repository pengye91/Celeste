import ShieldCheck from "lucide-react/dist/esm/icons/shield-check";
import ShieldAlert from "lucide-react/dist/esm/icons/shield-alert";
import Circle from "lucide-react/dist/esm/icons/circle";
import type { LucideIcon } from "lucide-react";
import type { FeatureCheck } from "@/lib/types";
import { Panel } from "@/components/ui/panel";
import { cn } from "@/lib/utils";

interface FeatureVerificationSummaryProps {
  loading: boolean;
  error: Error | null;
  summary: {
    total: number;
    pass: number;
    fail: number;
    not_exercised: number;
  } | null;
  /** Per-workflow feature checks for the "drill down" card. */
  checks: FeatureCheck[];
}

/**
 * Fleet-wide PASS / FAIL / NOT_EXERCISED grid. This is the *secondary*
 * pillar of the observatory per spec §6.13. Layout is intentionally
 * non-grid: a horizontal roll-up of counts, then a vertical list of
 * the individual feature checks so the eye can scan the names, not
 * navigate a 3x2 grid of equal-weight tiles.
 */
export function FeatureVerificationSummary({
  loading,
  error,
  summary,
  checks,
}: FeatureVerificationSummaryProps) {
  if (loading) {
    return (
      <Panel
        aria-label="Feature verification summary loading"
        className="space-y-4"
      >
        <div className="h-4 w-48 rounded-sm bg-space-600 animate-pulse" />
        <div className="flex gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-16 flex-1 rounded-md bg-space-700 animate-pulse"
            />
          ))}
        </div>
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-5 w-full rounded-sm bg-space-600 animate-pulse"
            />
          ))}
        </div>
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel
        role="alert"
        aria-label="Feature verification failed to load"
        className="border-mars-500/30 bg-mars-900/10"
      >
        <p className="text-mars-400 text-sm">
          Could not load feature verification:{" "}
          <span className="font-mono text-xs">
            {error instanceof Error ? error.message : "Unknown error"}
          </span>
        </p>
      </Panel>
    );
  }

  // Empty: no workflows at all.
  if (!summary || summary.total === 0) {
    return (
      <Panel
        aria-label="No feature verification data"
        className="text-center py-8"
      >
        <Circle
          className="w-6 h-6 mx-auto mb-2 text-comet-500 opacity-50"
          aria-hidden="true"
        />
        <p className="text-comet-400 text-sm">No workflows in the fleet yet</p>
        <p className="text-comet-600 text-xs mt-1">
          Feature checks appear once at least one workflow has run.
        </p>
      </Panel>
    );
  }

  const { pass, fail, not_exercised, total } = summary;

  return (
    <Panel
      aria-label="Feature verification summary"
      className="space-y-5"
    >
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <h2 className="text-base font-body font-medium text-comet-100">
          Feature Verification
        </h2>
        <span className="text-xs text-comet-500 font-mono">
          {total} check{total === 1 ? "" : "s"} across the fleet
        </span>
      </header>

      {/* Asymmetric roll-up: one main number (pass), two supporting (fail, not exercised). */}
      <div
        className="grid grid-cols-1 sm:grid-cols-3 gap-3"
        data-testid="fleet-counts"
      >
        <CountTile
          label="Pass"
          count={pass}
          variant="success"
          icon={ShieldCheck}
          emphasized
        />
        <CountTile
          label="Fail"
          count={fail}
          variant="danger"
          icon={ShieldAlert}
        />
        <CountTile
          label="Not exercised"
          count={not_exercised}
          variant="muted"
          icon={Circle}
        />
      </div>

      {/* Drill-down list: per-feature status. Sorted: fails first, then not_exercised, then pass. */}
      <div>
        <h3 className="text-xs uppercase tracking-wider text-comet-500 mb-2">
          Per-feature
        </h3>
        <ul className="divide-y divide-space-700 rounded-md border border-space-600 bg-space-800/40 overflow-hidden">
          {sortChecks(checks).map((check, idx) => (
            <FeatureRow key={`${check.name}-${idx}`} check={check} />
          ))}
        </ul>
      </div>
    </Panel>
  );
}

function CountTile({
  label,
  count,
  variant,
  icon: Icon,
  emphasized,
}: {
  label: string;
  count: number;
  variant: "success" | "danger" | "muted";
  icon: LucideIcon;
  emphasized?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-md border p-3 flex flex-col gap-1",
        "focus:outline-none focus:ring-2 focus:ring-aurora-500/50",
        variant === "success" &&
          "bg-aurora-500/10 border-aurora-500/30",
        variant === "danger" &&
          "bg-mars-500/10 border-mars-500/30",
        variant === "muted" &&
          "bg-space-800 border-space-600",
        emphasized && "sm:col-span-1"
      )}
      data-testid={`count-${variant}`}
    >
      <div className="flex items-center gap-1.5">
        <Icon
          className={cn(
            "w-3.5 h-3.5",
            variant === "success" && "text-aurora-400",
            variant === "danger" && "text-mars-400",
            variant === "muted" && "text-comet-500"
          )}
          aria-hidden="true"
        />
        <span
          className={cn(
            "text-[10px] uppercase tracking-wider",
            variant === "success" && "text-aurora-400",
            variant === "danger" && "text-mars-400",
            variant === "muted" && "text-comet-500"
          )}
        >
          {label}
        </span>
      </div>
      <span
        className={cn(
          "font-mono font-semibold",
          emphasized ? "text-2xl" : "text-xl",
          variant === "success" && "text-aurora-300",
          variant === "danger" && "text-mars-300",
          variant === "muted" && "text-comet-300"
        )}
      >
        {count}
      </span>
    </div>
  );
}

function FeatureRow({ check }: { check: FeatureCheck }) {
  const status = check.status;
  const variant =
    status === "pass" ? "success" : status === "fail" ? "danger" : "muted";
  const Icon =
    status === "pass" ? ShieldCheck : status === "fail" ? ShieldAlert : Circle;
  const label =
    status === "pass" ? "Pass" : status === "fail" ? "Fail" : "Not exercised";

  return (
    <li
      className={cn(
        "flex items-center gap-3 px-3 py-2",
        status === "fail" && "bg-mars-900/10"
      )}
      data-status={status}
    >
      <Icon
        className={cn(
          "w-3.5 h-3.5 shrink-0",
          status === "pass" && "text-aurora-400",
          status === "fail" && "text-mars-400",
          status === "not_exercised" && "text-comet-500"
        )}
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0">
        <p
          className={cn(
            "text-sm",
            status === "fail" ? "text-mars-300" : "text-comet-200"
          )}
        >
          {check.name}
        </p>
        {check.detail && (
          <p className="text-[11px] text-comet-500 mt-0.5">{check.detail}</p>
        )}
      </div>
      <span
        className={cn(
          "text-[10px] font-mono px-1.5 py-0.5 rounded-sm border",
          variant === "success" &&
            "bg-aurora-500/10 text-aurora-400 border-aurora-500/30",
          variant === "danger" &&
            "bg-mars-500/10 text-mars-400 border-mars-500/30",
          variant === "muted" &&
            "bg-space-700 text-comet-400 border-space-500"
        )}
      >
        {label}
      </span>
    </li>
  );
}

function sortChecks(checks: FeatureCheck[]): FeatureCheck[] {
  const order: Record<FeatureCheck["status"], number> = {
    fail: 0,
    not_exercised: 1,
    pass: 2,
  };
  return [...checks].sort((a, b) => order[a.status] - order[b.status]);
}
