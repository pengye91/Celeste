import { cn } from "@/lib/utils";
import { cva, type VariantProps } from "class-variance-authority";

const statusOrbVariants = cva("inline-block rounded-full", {
  variants: {
    variant: {
      idle: "bg-comet-500",
      running: "bg-aurora-500 animate-pulse-glow",
      success: "bg-aurora-500",
      warning: "bg-solar-500",
      error: "bg-mars-500",
      info: "bg-nebula-500",
    },
    size: {
      sm: "w-2 h-2",
      md: "w-2.5 h-2.5",
      lg: "w-3 h-3",
    },
  },
  defaultVariants: {
    variant: "idle",
    size: "md",
  },
});

export interface StatusOrbProps extends VariantProps<typeof statusOrbVariants> {
  className?: string;
  pulse?: boolean;
  /**
   * Optional accessible name. When provided, the orb is exposed to
   * assistive tech as `role="img"` with `aria-label`. When omitted,
   * the orb is treated as decorative (`aria-hidden="true"`) and the
   * surrounding text is expected to carry the meaning.
   */
  label?: string;
}

export function StatusOrb({ className, variant, size, pulse, label }: StatusOrbProps) {
  // Decorative by default — the orb is always paired with text in the
  // current call sites. When an explicit `label` is provided, expose
  // the orb as an img with that name.
  const a11yProps = label
    ? ({ role: "img", "aria-label": label } as const)
    : ({ "aria-hidden": "true" } as const);
  return (
    <span
      {...a11yProps}
      className={cn(
        statusOrbVariants({ variant, size }),
        pulse && variant === "running" && "animate-pulse-glow",
        className
      )}
    />
  );
}

export { statusOrbVariants };
