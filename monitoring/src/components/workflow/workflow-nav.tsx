import Link from "next/link";
import { cn } from "@/lib/utils";
import LayoutDashboard from "lucide-react/dist/esm/icons/layout-dashboard";
import Orbit from "lucide-react/dist/esm/icons/orbit";
import RotateCcw from "lucide-react/dist/esm/icons/rotate-ccw";
import Shield from "lucide-react/dist/esm/icons/shield";
import Boxes from "lucide-react/dist/esm/icons/boxes";
import Undo2 from "lucide-react/dist/esm/icons/undo-2";
import Hand from "lucide-react/dist/esm/icons/hand";

interface TabDef {
  href: string;
  label: string;
  icon: React.ElementType;
}

const TABS: TabDef[] = [
  { href: "./", label: "Overview", icon: LayoutDashboard },
  { href: "./constellation", label: "Constellation", icon: Orbit },
  { href: "./opa-loop", label: "OPA Loop", icon: RotateCcw },
  { href: "./security", label: "Security", icon: Shield },
  { href: "./workspaces", label: "Workspaces", icon: Boxes },
  { href: "./saga", label: "Saga", icon: Undo2 },
  { href: "./escalation", label: "Escalation", icon: Hand },
];

function TabLink({
  href,
  label,
  icon: Icon,
  isActive,
}: {
  href: string;
  label: string;
  icon: React.ElementType;
  isActive: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2",
        isActive
          ? "text-aurora-400 border-aurora-500"
          : "text-comet-400 border-transparent hover:text-comet-200 hover:border-comet-500"
      )}
      aria-current={isActive ? "page" : undefined}
    >
      <Icon className="w-4 h-4 shrink-0" />
      <span className="whitespace-nowrap">{label}</span>
    </Link>
  );
}

export function WorkflowNav({ activeTab }: { activeTab: "overview" | "constellation" | "opa-loop" | "security" | "workspaces" | "saga" | "escalation" }) {
  return (
    <nav className="flex items-center border-b border-space-600/50 overflow-x-auto scrollbar-hide" aria-label="Workflow tabs">
      {TABS.map((tab) => {
        const isActive = activeTab === tab.label.toLowerCase().replace(/ /g, "-");
        return (
          <TabLink
            key={tab.label}
            href={tab.href}
            label={tab.label}
            icon={tab.icon}
            isActive={isActive}
          />
        );
      })}
    </nav>
  );
}
