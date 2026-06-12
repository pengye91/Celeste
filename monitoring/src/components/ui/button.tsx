import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { Slot } from "@radix-ui/react-slot";
import { forwardRef } from "react";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-body text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-aurora-500 focus-visible:ring-offset-2 focus-visible:ring-offset-space-void disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-space-700 text-comet-100 hover:bg-space-600 border border-space-500 hover:border-space-400",
        primary:
          "bg-aurora-500 text-space-void hover:bg-aurora-400 shadow-glow",
        ghost:
          "bg-transparent text-comet-300 hover:bg-space-700 hover:text-comet-100",
        danger:
          "bg-mars-500/10 text-mars-400 border border-mars-500/30 hover:bg-mars-500/20 hover:border-mars-500/50",
        subtle:
          "bg-space-800 text-comet-400 hover:bg-space-700 hover:text-comet-200",
      },
      size: {
        default: "h-9 px-4 py-2 rounded-md",
        sm: "h-7 px-3 py-1 text-xs rounded-sm",
        lg: "h-11 px-6 py-2.5 rounded-lg",
        icon: "h-9 w-9 rounded-md",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
