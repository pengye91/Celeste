"use client";

import { useState, type FormEvent } from "react";
import { Panel } from "@/components/ui/panel";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useRegisterAgent } from "@/hooks/useAgents";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import Plus from "lucide-react/dist/esm/icons/plus";
import Trash2 from "lucide-react/dist/esm/icons/trash-2";
import Loader2 from "lucide-react/dist/esm/icons/loader-2";
import Plug from "lucide-react/dist/esm/icons/plug";
import Eye from "lucide-react/dist/esm/icons/eye";
import EyeOff from "lucide-react/dist/esm/icons/eye-off";
import type { RegisterAgentRequest } from "@/lib/types";

type MetadataPair = { id: string; key: string; value: string };

function makeId(): string {
  return Math.random().toString(36).slice(2, 9);
}

/**
 * Inline register-agent form.
 *
 * Contract from foundation:
 *   - URL is required and validated as a non-empty string that begins
 *     with http:// or https:// (looser than the network call but tighter
 *     than "anything typed" so the operator gets feedback early).
 *   - Auth token is optional and masked.
 *   - Metadata is a key/value pair repeater; rows with empty keys are
 *     filtered before submission.
 *
 * Feedback per spec:
 *   - On success: a toast announces registration.
 *   - On 4xx: an inline field-level error appears below the form
 *     (the user can fix and retry without losing input).
 *   - On 5xx / network failure: a toast is shown instead.
 *
 * The parent receives a live region message via `onStatusChange` so
 * screen-reader users hear "Agent registered" or "Registration failed".
 */
export interface RegisterAgentFormProps {
  /** Optional override; if true, the form starts expanded regardless of context. */
  defaultExpanded?: boolean;
  /** Optional className for the outer Panel. */
  className?: string;
  /**
   * Notifies the parent of status transitions for an aria-live region.
   * The parent owns the live region element; the form just reports state.
   */
  onStatusChange?: (status: "idle" | "success" | "error", message?: string) => void;
}

function isLikelyUrl(value: string): boolean {
  if (!value) return false;
  return /^https?:\/\/[^\s]+$/i.test(value.trim());
}

function serializeMetadata(pairs: MetadataPair[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const pair of pairs) {
    const key = pair.key.trim();
    if (!key) continue;
    out[key] = pair.value;
  }
  return out;
}

export function RegisterAgentForm({
  defaultExpanded = false,
  className,
  onStatusChange,
}: RegisterAgentFormProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [authToken, setAuthToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [metadata, setMetadata] = useState<MetadataPair[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const { toast } = useToast();
  const { mutate, isPending, error, isError } = useRegisterAgent();

  const handleAddMetadata = () => {
    setMetadata((prev) => [...prev, { id: makeId(), key: "", value: "" }]);
  };

  const handleRemoveMetadata = (id: string) => {
    setMetadata((prev) => prev.filter((p) => p.id !== id));
  };

  const handleMetadataChange = (
    id: string,
    field: "key" | "value",
    next: string,
  ) => {
    setMetadata((prev) =>
      prev.map((p) => (p.id === id ? { ...p, [field]: next } : p)),
    );
  };

  const reset = () => {
    setUrl("");
    setAuthToken("");
    setMetadata([]);
    setUrlError(null);
    setSubmitError(null);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitError(null);

    if (!isLikelyUrl(url)) {
      setUrlError("Enter a valid URL starting with http:// or https://");
      onStatusChange?.("error", "Registration failed: invalid URL");
      return;
    }
    setUrlError(null);

    const body: RegisterAgentRequest = {
      url: url.trim(),
    };
    if (authToken.trim()) {
      body.auth_token = authToken.trim();
    }
    const meta = serializeMetadata(metadata);
    if (Object.keys(meta).length > 0) {
      body.metadata = meta;
    }

    mutate(body, {
      onSuccess: () => {
        toast({
          message: "Agent registered",
          variant: "success",
        });
        onStatusChange?.("success", "Agent registered");
        reset();
        setExpanded(false);
      },
      onError: (err) => {
        // fetchJson throws plain Error for network / 5xx; the API
        // helper throws CelesteAPIError (status) for 4xx. We can tell
        // them apart by checking the message shape or by passing
        // custom error metadata. For now, treat all thrown errors
        // as a single category and surface a user-friendly line.
        const message =
          err instanceof Error ? err.message : "Unknown error";
        const isClientError = /API 4\d\d/.test(message);
        if (isClientError) {
          // Strip the "API 4xx: " prefix for the operator-facing message.
          const inline = message.replace(/^API 4\d\d:\s*/, "") || "Invalid request";
          setSubmitError(inline);
        } else {
          toast({
            message: "Registration failed. Check connectivity and retry.",
            variant: "error",
          });
        }
        onStatusChange?.("error", `Registration failed: ${message}`);
      },
    });
  };

  return (
    <Panel
      data-testid="register-agent-form"
      className={cn("p-4 space-y-4", className)}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Plug className="w-4 h-4 text-aurora-400" aria-hidden="true" />
          <h2 className="text-sm font-body font-medium text-comet-200">
            Register a new agent
          </h2>
        </div>
        {!defaultExpanded && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            aria-controls="register-agent-form-body"
          >
            {expanded ? "Hide" : "Show form"}
          </Button>
        )}
      </div>

      {(expanded || defaultExpanded) && (
        <form
          id="register-agent-form-body"
          onSubmit={handleSubmit}
          className="space-y-4"
          noValidate
        >
          {/* URL */}
          <div className="space-y-1.5">
            <label
              htmlFor="agent-url"
              className="text-xs font-body font-medium text-comet-300"
            >
              Agent URL
              <span className="text-mars-400 ml-1" aria-hidden="true">
                *
              </span>
            </label>
            <Input
              id="agent-url"
              name="url"
              type="url"
              required
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (urlError) setUrlError(null);
              }}
              placeholder="https://agent.example.com"
              aria-invalid={urlError ? "true" : "false"}
              aria-describedby={urlError ? "agent-url-error" : undefined}
              disabled={isPending}
            />
            {urlError && (
              <p
                id="agent-url-error"
                role="alert"
                className="text-xs text-mars-400"
              >
                {urlError}
              </p>
            )}
          </div>

          {/* Auth token */}
          <div className="space-y-1.5">
            <label
              htmlFor="agent-auth-token"
              className="text-xs font-body font-medium text-comet-300"
            >
              Auth token{" "}
              <span className="text-comet-500 text-[10px]">(optional)</span>
            </label>
            <div className="relative">
              <Input
                id="agent-auth-token"
                name="auth_token"
                type={showToken ? "text" : "password"}
                value={authToken}
                onChange={(e) => setAuthToken(e.target.value)}
                placeholder="••••••••"
                autoComplete="off"
                disabled={isPending}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowToken((v) => !v)}
                aria-label={showToken ? "Hide auth token" : "Show auth token"}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-comet-500 hover:text-aurora-400 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-aurora-500/50 rounded-sm"
              >
                {showToken ? (
                  <EyeOff className="w-4 h-4" aria-hidden="true" />
                ) : (
                  <Eye className="w-4 h-4" aria-hidden="true" />
                )}
              </button>
            </div>
          </div>

          {/* Metadata repeater */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-body font-medium text-comet-300">
                Metadata{" "}
                <span className="text-comet-500 text-[10px]">(optional)</span>
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleAddMetadata}
                disabled={isPending}
              >
                <Plus className="w-3.5 h-3.5" aria-hidden="true" />
                Add pair
              </Button>
            </div>
            {metadata.length > 0 && (
              <div className="space-y-2">
                {metadata.map((pair) => (
                  <div
                    key={pair.id}
                    className="grid grid-cols-[1fr_1fr_auto] gap-2 items-start"
                  >
                    <Input
                      aria-label={`Metadata key ${pair.id}`}
                      placeholder="key"
                      value={pair.key}
                      onChange={(e) =>
                        handleMetadataChange(pair.id, "key", e.target.value)
                      }
                      disabled={isPending}
                    />
                    <Input
                      aria-label={`Metadata value ${pair.id}`}
                      placeholder="value"
                      value={pair.value}
                      onChange={(e) =>
                        handleMetadataChange(pair.id, "value", e.target.value)
                      }
                      disabled={isPending}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => handleRemoveMetadata(pair.id)}
                      aria-label={`Remove metadata pair ${pair.key || "row"}`}
                      disabled={isPending}
                    >
                      <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Inline submit-level error (4xx) */}
          {submitError && (
            <div
              role="alert"
              className="text-xs text-mars-400 bg-mars-500/10 border border-mars-500/20 rounded-md px-3 py-2"
            >
              {submitError}
            </div>
          )}

          <div className="flex items-center gap-2 pt-1">
            <Button
              type="submit"
              variant="primary"
              size="default"
              disabled={isPending}
            >
              {isPending ? (
                <>
                  <Loader2
                    className="w-4 h-4 motion-safe:animate-spin"
                    aria-hidden="true"
                  />
                  Registering…
                </>
              ) : (
                <>
                  <Plug className="w-4 h-4" aria-hidden="true" />
                  Register agent
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="default"
              onClick={reset}
              disabled={isPending}
            >
              Clear
            </Button>
            {isError && !submitError && (
              <span
                className="text-xs text-mars-400"
                role="alert"
              >
                {error instanceof Error
                  ? error.message.replace(/^API [45]\d\d:\s*/, "")
                  : "Registration failed"}
              </span>
            )}
          </div>
        </form>
      )}
    </Panel>
  );
}
