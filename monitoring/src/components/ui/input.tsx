import { cn } from "@/lib/utils";
import { forwardRef } from "react";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-9 w-full rounded-md border border-space-500 bg-space-800 px-3 py-1 text-sm text-comet-100 shadow-sm transition-colors",
          "placeholder:text-comet-500",
          "focus-visible:outline-none focus-visible:border-aurora-500 focus-visible:ring-2 focus-visible:ring-aurora-500 focus-visible:ring-offset-2 focus-visible:ring-offset-space-void",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
