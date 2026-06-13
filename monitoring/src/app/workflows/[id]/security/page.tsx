"use client";

import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { StatusOrb } from "@/components/ui/status-orb";
import {
  useWorkflow,
  useWorkflowMetrics,
} from "@/hooks/useWorkflow";
import { useWorkflowEvents } from "@/hooks/useWorkflowEvents";
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { formatTimestamp } from "@/lib/format";
import { WorkflowNav } from "@/components/workflow/workflow-nav";
import { cn } from "@/lib/utils";
import ArrowLeft from "lucide-react/dist/esm/icons/arrow-left";
import Copy from "lucide-react/dist/esm/icons/copy";
import Shield from "lucide-react/dist/esm/icons/shield";
import ShieldAlert from "lucide-react/dist/esm/icons/shield-alert";
import ShieldCheck from "lucide-react/dist/esm/icons/shield-check";
import AlertTriangle from "lucide-react/dist/esm/icons/alert-triangle";
import Activity from "lucide-react/dist/esm/icons/activity";
import Eye from "lucide-react/dist/esm/icons/eye";
import Tag from "lucide-react/dist/esm/icons/tag";
import Fingerprint from "lucide-react/dist/esm/icons/fingerprint-pattern";
import Siren from "lucide-react/dist/esm/icons/siren";
import FileJson from "lucide-react/dist/esm/icons/file-json";
import Link from "next/link";
import { Suspense, use, useState, useMemo } from "react";

// ------------------------------------------------------------------
// Types
// ------------------------------------------------------------------

interface AuditEvent {
  id: string;
  event_type: string;
  event_data: Record<string, unknown> | null;
  timestamp: string;
}

interface ParsedAudit {
  verdict: "safe" | "blocked" | "unknown";
  risk: string;
  reason: string;
  tool: string;
  argumentsSnippet: string;
  threats: string[];
  timestamp: string;
  eventId: string;
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function CopyButton({ text }: { text: string }) {
  const { copy } = useCopyToClipboard();
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        copy(text, "workflow ID");
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-1 text-xs font-mono text-comet-500 hover:text-aurora-400 transition-colors"
      title="Copy ID"
    >
      <Copy className="w-3 h-3" />
      {copied ? "Copied" : text.slice(0, 8)}
    </button>
  );
}

function getVerdict(eventData: Record<string, unknown> | null): "safe" | "blocked" | "unknown" {
  if (!eventData) return "unknown";
  const result = eventData.result;
  if (typeof result === "string") {
    if (result.toLowerCase() === "safe") return "safe";
    if (result.toLowerCase() === "blocked" || result.toLowerCase() === "unsafe") return "blocked";
  }
  const verdict = eventData.verdict;
  if (typeof verdict === "string") {
    if (verdict.toLowerCase() === "safe") return "safe";
    if (verdict.toLowerCase() === "blocked" || verdict.toLowerCase() === "unsafe") return "blocked";
  }
  return "unknown";
}

function getRiskLevel(eventData: Record<string, unknown> | null): string {
  if (!eventData) return "unknown";
  const risk = eventData.risk;
  if (typeof risk === "string") return risk;
  const riskLevel = eventData.risk_level;
  if (typeof riskLevel === "string") return riskLevel;
  return "unknown";
}

function getReason(eventData: Record<string, unknown> | null): string {
  if (!eventData) return "No reason recorded";
  const reason = eventData.reason;
  if (typeof reason === "string") return reason;
  const reasoning = eventData.reasoning;
  if (typeof reasoning === "string") return reasoning;
  const explanation = eventData.explanation;
  if (typeof explanation === "string") return explanation;
  return "No reason recorded";
}

function getToolName(eventData: Record<string, unknown> | null): string {
  if (!eventData) return "Unknown tool";
  const tool = eventData.tool;
  if (typeof tool === "string") return tool;
  const toolName = eventData.tool_name;
  if (typeof toolName === "string") return toolName;
  const command = eventData.command;
  if (typeof command === "string") return command;
  return "Unknown tool";
}

function getArgumentsSnippet(eventData: Record<string, unknown> | null): string {
  if (!eventData) return "—";
  const args = eventData.arguments ?? eventData.args ?? eventData.tool_args;
  if (typeof args === "string") return args;
  if (typeof args === "object" && args !== null) {
    try {
      const json = JSON.stringify(args);
      if (json.length > 120) return json.slice(0, 120) + "…";
      return json;
    } catch {
      return "(unserializable)";
    }
  }
  return "—";
}

function getThreats(eventData: Record<string, unknown> | null): string[] {
  if (!eventData) return [];
  const threats = eventData.threats;
  if (Array.isArray(threats)) {
    return threats.filter((t): t is string => typeof t === "string");
  }
  return [];
}

function parseAuditEvents(events: AuditEvent[]): ParsedAudit[] {
  return events.map((e) => ({
    verdict: getVerdict(e.event_data),
    risk: getRiskLevel(e.event_data),
    reason: getReason(e.event_data),
    tool: getToolName(e.event_data),
    argumentsSnippet: getArgumentsSnippet(e.event_data),
    threats: getThreats(e.event_data),
    timestamp: e.timestamp,
    eventId: e.id,
  }));
}

function getRiskVariant(risk: string): "default" | "success" | "warning" | "danger" | "info" | "muted" {
  const r = risk.toLowerCase();
  if (r === "high" || r === "critical" || r === "severe") return "danger";
  if (r === "medium" || r === "moderate") return "warning";
  if (r === "low" || r === "minor") return "info";
  if (r === "none" || r === "safe") return "success";
  return "default";
}

function getRiskIconElement(risk: string): React.ReactNode {
  const r = risk.toLowerCase();
  if (r === "high" || r === "critical" || r === "severe") {
    return <Siren className="w-3 h-3 mr-1" aria-hidden="true" />;
  }
  if (r === "medium" || r === "moderate") {
    return <AlertTriangle className="w-3 h-3 mr-1" aria-hidden="true" />;
  }
  if (r === "low" || r === "minor") {
    return <ShieldAlert className="w-3 h-3 mr-1" aria-hidden="true" />;
  }
  return <Shield className="w-3 h-3 mr-1" aria-hidden="true" />;
}

// ------------------------------------------------------------------
// Coverage Meter (SVG arc gauge)
// ------------------------------------------------------------------

function CoverageMeter({
  passRate,
  safeCount,
  totalCount,
}: {
  passRate: number | null;
  safeCount: number;
  totalCount: number;
}) {
  const radius = 56;
  const stroke = 8;
  const normalizedRadius = radius - stroke * 2;
  const circumference = normalizedRadius * 2 * Math.PI;
  const arcLength = circumference * 0.75; // 270-degree arc
  const rate = passRate ?? 0;
  const strokeDashoffset = arcLength - rate * arcLength;

  const colorClass =
    rate >= 0.9
      ? "text-nebula-500"
      : rate >= 0.7
      ? "text-solar-500"
      : "text-mars-500";

  const trackColor = "text-space-700";

  return (
    <div className="flex items-center gap-6">
      <div className="relative w-32 h-32 shrink-0" aria-label="Audit coverage gauge">
        <svg
          height={radius * 2}
          width={radius * 2}
          viewBox={`0 0 ${radius * 2} ${radius * 2}`}
          className="rotate-[135deg]"
        >
          {/* Track arc */}
          <circle
            stroke="currentColor"
            fill="transparent"
            strokeWidth={stroke}
            strokeDasharray={`${arcLength} ${circumference}`}
            r={normalizedRadius}
            cx={radius}
            cy={radius}
            className={trackColor}
            strokeLinecap="round"
          />
          {/* Progress arc */}
          <circle
            stroke="currentColor"
            fill="transparent"
            strokeWidth={stroke}
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeDashoffset={strokeDashoffset}
            r={normalizedRadius}
            cx={radius}
            cy={radius}
            className={cn(colorClass, "transition-all duration-700")}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("text-2xl font-mono font-semibold", colorClass)}>
            {totalCount > 0 ? `${Math.round(rate * 100)}%` : "—"}
          </span>
          <span className="text-[10px] text-comet-500 uppercase tracking-wider">Coverage</span>
        </div>
      </div>
      <div className="space-y-1">
        <div className="flex items-center gap-2 text-sm text-comet-300">
          <ShieldCheck className="w-4 h-4 text-nebula-400" aria-hidden="true" />
          <span>{safeCount} safe</span>
        </div>
        <div className="flex items-center gap-2 text-sm text-comet-300">
          <ShieldAlert className="w-4 h-4 text-mars-400" aria-hidden="true" />
          <span>{totalCount - safeCount} blocked</span>
        </div>
        <div className="flex items-center gap-2 text-sm text-comet-500">
          <Activity className="w-4 h-4" aria-hidden="true" />
          <span>{totalCount} total audited</span>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------
// Verdict Card
// ------------------------------------------------------------------

function VerdictCard({
  audit,
}: {
  audit: ParsedAudit;
}) {
  const isBlocked = audit.verdict === "blocked";
  const riskIcon = getRiskIconElement(audit.risk);

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-all duration-200",
        isBlocked
          ? "bg-mars-900/20 border-mars-500/30 hover:border-mars-500/60"
          : "bg-space-800 border-space-600 hover:border-space-500"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          {isBlocked ? (
            <>
              <ShieldAlert className="w-4 h-4 text-mars-400" aria-hidden="true" />
              <span className="text-sm font-medium text-mars-400">Blocked</span>
            </>
          ) : audit.verdict === "safe" ? (
            <>
              <ShieldCheck className="w-4 h-4 text-nebula-400" aria-hidden="true" />
              <span className="text-sm font-medium text-nebula-400">Safe</span>
            </>
          ) : (
            <>
              <Shield className="w-4 h-4 text-comet-400" aria-hidden="true" />
              <span className="text-sm font-medium text-comet-400">Unknown</span>
            </>
          )}
        </div>
        <Badge variant={getRiskVariant(audit.risk)} className="text-[10px]">
          {riskIcon}
          {audit.risk}
        </Badge>
      </div>

      <div className="mt-3 space-y-2">
        <div className="flex items-center gap-2 text-xs text-comet-400">
          <Fingerprint className="w-3 h-3" aria-hidden="true" />
          <span className="font-mono">{audit.tool}</span>
        </div>
        {audit.argumentsSnippet !== "—" && (
          <div className="flex items-start gap-2 text-xs text-comet-500">
            <FileJson className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
            <code className="font-mono break-all">{audit.argumentsSnippet}</code>
          </div>
        )}
        <p className="text-xs text-comet-300 leading-relaxed">{audit.reason}</p>
      </div>

      <div className="mt-3 text-[10px] font-mono text-comet-600">
        {formatTimestamp(audit.timestamp)}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------
// Main Page
// ------------------------------------------------------------------

export default function SecurityAuditPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <Suspense fallback={<Shell><div className="space-y-4"><div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" /></div></Shell>}>
      <SecurityAuditPageInner params={params} />
    </Suspense>
  );
}

function SecurityAuditPageInner({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: workflow, isLoading: wfLoading, error: wfError } = useWorkflow(id);
  const { data: metrics, isLoading: metricsLoading } = useWorkflowMetrics(id);
  const {
    data: auditEvents,
    isLoading: eventsLoading,
    error: eventsError,
  } = useWorkflowEvents(id, {
    event_type: "SECURITY_AUDIT",
    limit: 200,
  });

  const audits = useMemo(() => {
    if (!auditEvents) return [];
    return parseAuditEvents(auditEvents);
  }, [auditEvents]);

  const blockedAudits = useMemo(() => audits.filter((a) => a.verdict === "blocked"), [audits]);
  const safeCount = useMemo(() => audits.filter((a) => a.verdict === "safe").length, [audits]);
  const totalCount = audits.length;

  const allThreats = useMemo(() => {
    const set = new Set<string>();
    for (const audit of audits) {
      for (const threat of audit.threats) {
        if (threat.trim()) set.add(threat.trim());
      }
    }
    return Array.from(set).sort();
  }, [audits]);

  const isLoading = wfLoading || metricsLoading || eventsLoading;
  const error = wfError || eventsError;

  // Pass rate from metrics if available, otherwise computed from events
  const passRate = useMemo(() => {
    if (metrics?.security_pass_rate !== null && metrics?.security_pass_rate !== undefined) {
      return metrics.security_pass_rate;
    }
    if (totalCount === 0) return null;
    return safeCount / totalCount;
  }, [metrics, safeCount, totalCount]);

  return (
    <Shell>
      <div className="space-y-6">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-comet-500">
          <Link
            href="/workflows"
            className="flex items-center gap-1 hover:text-aurora-400 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Workflows
          </Link>
          <span>/</span>
          <Link
            href={`/workflows/${id}`}
            className="hover:text-aurora-400 transition-colors"
          >
            {workflow?.name ?? id.slice(0, 8)}
          </Link>
          <span>/</span>
          <span className="text-comet-300">Security Audit</span>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="space-y-4">
            <div className="h-8 w-64 bg-space-700/50 rounded animate-pulse" />
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="h-48 bg-space-700/50 rounded animate-pulse" />
              <div className="h-48 bg-space-700/50 rounded animate-pulse lg:col-span-2" />
            </div>
          </div>
        )}

        {/* Error */}
        {!isLoading && error && (
          <Panel className="text-center py-12">
            <p className="text-mars-400 text-sm">
              Failed to load security audit data: {error instanceof Error ? error.message : "Unknown error"}
            </p>
          </Panel>
        )}

        {/* Empty: no workflow */}
        {!isLoading && !error && !workflow && (
          <Panel className="text-center py-12">
            <p className="text-comet-500">Workflow not found</p>
          </Panel>
        )}

        {/* Empty: no audit events */}
        {!isLoading && !error && workflow && totalCount === 0 && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-start gap-4">
                <StatusOrb
                  variant={
                    workflow.status === "running"
                      ? "running"
                      : workflow.status === "completed"
                      ? "success"
                      : workflow.status === "failed"
                      ? "error"
                      : workflow.status === "paused"
                      ? "warning"
                      : "idle"
                  }
                  size="lg"
                  pulse={workflow.status === "running"}
                />
                <div>
                  <h1 className="text-3xl font-display text-comet-100">
                    {workflow.name}
                  </h1>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <Badge
                      variant={
                        workflow.status === "running"
                          ? "success"
                          : workflow.status === "completed"
                          ? "success"
                          : workflow.status === "failed"
                          ? "danger"
                          : workflow.status === "paused"
                          ? "warning"
                          : "muted"
                      }
                    >
                      {workflow.status}
                    </Badge>
                    <span className="text-xs font-mono text-comet-500">
                      {workflow.id}
                    </span>
                    <CopyButton text={workflow.id} />
                  </div>
                </div>
              </div>
            </div>

            {/* Tab navigation */}
            <WorkflowNav activeTab="security" />

            <Panel className="text-center py-12">
              <Eye className="w-6 h-6 mx-auto mb-2 text-comet-500 opacity-50" aria-hidden="true" />
              <p className="text-comet-500 text-sm">No audited calls</p>
              <p className="text-comet-600 text-xs mt-1">
                Security audits appear when tool calls are evaluated by the security pipeline.
              </p>
            </Panel>
          </div>
        )}

        {/* Main content */}
        {!isLoading && !error && workflow && totalCount > 0 && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex items-start gap-4">
                <StatusOrb
                  variant={
                    workflow.status === "running"
                      ? "running"
                      : workflow.status === "completed"
                      ? "success"
                      : workflow.status === "failed"
                      ? "error"
                      : workflow.status === "paused"
                      ? "warning"
                      : "idle"
                  }
                  size="lg"
                  pulse={workflow.status === "running"}
                />
                <div>
                  <h1 className="text-3xl font-display text-comet-100">
                    {workflow.name}
                  </h1>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <Badge
                      variant={
                        workflow.status === "running"
                          ? "success"
                          : workflow.status === "completed"
                          ? "success"
                          : workflow.status === "failed"
                          ? "danger"
                          : workflow.status === "paused"
                          ? "warning"
                          : "muted"
                      }
                    >
                      {workflow.status}
                    </Badge>
                    <span className="text-xs font-mono text-comet-500">
                      {workflow.id}
                    </span>
                    <CopyButton text={workflow.id} />
                  </div>
                </div>
              </div>
            </div>

            {/* Tab navigation */}
            <WorkflowNav activeTab="security" />

            {/* Coverage meter + summary */}
            <Panel variant="elevated" padding="lg">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <CoverageMeter
                  passRate={passRate}
                  safeCount={safeCount}
                  totalCount={totalCount}
                />
                <div
                  className="text-sm text-comet-300 space-y-1"
                  aria-live="polite"
                  aria-atomic="true"
                >
                  <p>
                    <span className="text-comet-500">Blocked calls:</span>{" "}
                    <span className="font-mono text-mars-400">{blockedAudits.length}</span>
                  </p>
                  <p>
                    <span className="text-comet-500">Unique threats:</span>{" "}
                    <span className="font-mono text-solar-400">{allThreats.length}</span>
                  </p>
                  {metrics?.security_pass_rate !== null && metrics?.security_pass_rate !== undefined && (
                    <p className="text-[10px] text-comet-600">
                      From metrics endpoint
                    </p>
                  )}
                </div>
              </div>
            </Panel>

            {/* Two-column layout: blocked list + threat cloud / verdict cards */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Left: Blocked calls list */}
              <div className="space-y-4">
                <h2 className="text-lg font-body font-medium text-comet-100 flex items-center gap-2">
                  <ShieldAlert className="w-5 h-5 text-mars-400" aria-hidden="true" />
                  Blocked Calls
                </h2>
                {blockedAudits.length === 0 ? (
                  <Panel className="text-center py-8">
                    <ShieldCheck className="w-5 h-5 mx-auto mb-2 text-nebula-400" aria-hidden="true" />
                    <p className="text-sm text-comet-400">All calls passed security audit</p>
                  </Panel>
                ) : (
                  <div className="space-y-3">
                    {blockedAudits.map((audit) => (
                      <div
                        key={audit.eventId}
                        className="rounded-lg border border-mars-500/30 bg-mars-900/10 p-3 space-y-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-mono text-comet-300">{audit.tool}</span>
                          <Badge variant="danger" className="text-[10px]">
                            {audit.risk}
                          </Badge>
                        </div>
                        {audit.argumentsSnippet !== "—" && (
                          <code className="block text-[10px] font-mono text-comet-500 break-all">
                            {audit.argumentsSnippet}
                          </code>
                        )}
                        <p className="text-xs text-mars-400">{audit.reason}</p>
                        <div className="text-[10px] font-mono text-comet-600">
                          {formatTimestamp(audit.timestamp)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Threat tag cloud */}
                <h2 className="text-lg font-body font-medium text-comet-100 flex items-center gap-2 pt-2">
                  <Tag className="w-5 h-5 text-solar-400" aria-hidden="true" />
                  Threats Detected
                </h2>
                {allThreats.length === 0 ? (
                  <Panel className="text-center py-6">
                    <p className="text-sm text-comet-400">No threats tagged</p>
                  </Panel>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {allThreats.map((threat) => (
                      <Badge key={threat} variant="warning" className="text-[10px]">
                        {threat}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              {/* Right: Verdict cards */}
              <div className="lg:col-span-2 space-y-4">
                <h2 className="text-lg font-body font-medium text-comet-100 flex items-center gap-2">
                  <Shield className="w-5 h-5 text-aurora-400" aria-hidden="true" />
                  Audit Verdicts
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {audits.map((audit) => (
                    <VerdictCard
                      key={audit.eventId}
                      audit={audit}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}
