import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { StatusOrb } from "@/components/ui/status-orb";

/**
 * Top-level route-segment loading shell.
 *
 * The dashboard and per-page components already render their own
 * skeletons on data fetches. This global file is the fallback used
 * during initial route transitions before per-page skeletons mount.
 * It is intentionally minimal — a centred status orb inside the
 * observatory Shell, signalling that the next surface is on its way.
 */
export default function GlobalLoading() {
  return (
    <Shell>
      <div className="flex items-center justify-center min-h-[60vh]">
        <Panel variant="subtle" padding="lg" className="max-w-sm w-full">
          <div className="flex flex-col items-center text-center gap-4">
            <div className="flex items-center gap-3">
              <StatusOrb
                variant="running"
                size="lg"
                pulse
                label="Loading"
              />
              <span className="font-mono text-xs uppercase tracking-widest text-aurora-400">
                Establishing uplink
              </span>
            </div>
            <p className="text-sm text-comet-500">
              Aligning instruments…
            </p>
          </div>
        </Panel>
      </div>
    </Shell>
  );
}
