"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import LayoutDashboard from "lucide-react/dist/esm/icons/layout-dashboard";
import GitBranch from "lucide-react/dist/esm/icons/git-branch";
import Bot from "lucide-react/dist/esm/icons/bot";
import Telescope from "lucide-react/dist/esm/icons/telescope";
import { cn } from "@/lib/utils";
import { comboToReadable } from "@/lib/shortcuts";

const navItems: {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  shortcut: string;
}[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, shortcut: "Ctrl+Shift+D" },
  { href: "/workflows", label: "Workflows", icon: GitBranch, shortcut: "Ctrl+Shift+W" },
  { href: "/agents", label: "Agents", icon: Bot, shortcut: "Ctrl+Shift+A" },
  { href: "/observatory", label: "Observatory", icon: Telescope, shortcut: "Ctrl+Shift+O" },
];

export function SideRail({ className }: { className?: string }) {
  const [expanded, setExpanded] = useState(false);
  const pathname = usePathname();

  return (
    <nav
      className={cn(
        "h-[calc(100vh-3.5rem)] sticky top-14 border-r border-space-500 bg-space-900/60 backdrop-blur-sm flex flex-col py-3 transition-all duration-200",
        expanded ? "w-44" : "w-14",
        className
      )}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
    >
      <ul className="flex flex-col gap-1 px-2">
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(item.href + "/");
          const Icon = item.icon;
          const readable = comboToReadable(item.shortcut);
          const title = `${item.label} (${readable})`;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-keyshortcuts={item.shortcut}
                title={title}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 h-10 min-h-[44px] rounded-md px-2.5 transition-colors",
                  isActive
                    ? "bg-aurora-500/10 text-aurora-400 border border-aurora-500/20"
                    : "text-comet-400 hover:bg-space-700 hover:text-comet-200"
                )}
              >
                <Icon className="w-[18px] h-[18px] shrink-0" aria-hidden="true" />
                <span
                  className={cn(
                    "text-sm font-body whitespace-nowrap transition-opacity duration-150",
                    expanded ? "opacity-100" : "opacity-0 w-0 overflow-hidden"
                  )}
                >
                  {item.label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
