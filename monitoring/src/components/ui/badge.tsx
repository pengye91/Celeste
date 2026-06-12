import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-mono font-medium rounded-sm border",
  {
    variants: {
      variant: {
        default:
          "bg-space-700 text-comet-300 border-space-500",
        success:
          "bg-aurora-500/10 text-aurora-400 border-aurora-500/30",
        warning:
          "bg-solar-500/10 text-solar-400 border-solar-500/30",
        danger:
          "bg-mars-500/10 text-mars-400 border-mars-500/30",
        info:
          "bg-nebula-500/10 text-nebula-400 border-nebula-500/30",
        muted:
          "bg-space-800 text-comet-500 border-space-600",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, className }))} {...props} />
  );
}

export { badgeVariants };
