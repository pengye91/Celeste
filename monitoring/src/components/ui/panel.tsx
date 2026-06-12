import { cn } from "@/lib/utils";
import { forwardRef } from "react";

export interface PanelProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "elevated" | "subtle";
  padding?: "none" | "sm" | "md" | "lg";
}

const Panel = forwardRef<HTMLDivElement, PanelProps>(
  ({ className, variant = "default", padding = "md", children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          "rounded-lg border transition-colors",
          {
            "bg-space-800 border-space-500": variant === "default",
            "bg-space-700 border-space-400 shadow-md": variant === "elevated",
            "bg-space-900 border-space-600": variant === "subtle",
            "p-0": padding === "none",
            "p-3": padding === "sm",
            "p-4": padding === "md",
            "p-6": padding === "lg",
          },
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
Panel.displayName = "Panel";

export { Panel };
