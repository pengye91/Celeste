// Deep-import shim for lucide-react. The package's barrel d.ts
// (node_modules/lucide-react/dist/lucide-react.d.ts) declares every
// icon, but the per-icon ESM files (e.g. dist/esm/icons/activity.mjs)
// do not ship their own .d.ts. Without this shim, TypeScript fails
// to resolve the module path. Each icon module's runtime default
// export is the same component that the barrel re-exports.

declare module "lucide-react/dist/esm/icons/*" {
  import type { ForwardRefExoticComponent, RefAttributes, LucideProps } from "lucide-react";
  const Icon: ForwardRefExoticComponent<
    Omit<LucideProps, "ref"> & RefAttributes<SVGSVGElement>
  >;
  export default Icon;
}
