import Link from "next/link";
import { Shell } from "@/components/shell/shell";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import Orbit from "lucide-react/dist/esm/icons/orbit";

/**
 * 404 page.
 *
 * Replaces Next's default on-brand page. Matches the observatory
 * aesthetic — large display heading, line-art orbit icon, and a
 * single primary action back to the dashboard.
 */
export default function NotFound() {
  return (
    <Shell>
      <div className="flex items-center justify-center min-h-[60vh]">
        <Panel variant="elevated" padding="lg" className="max-w-md w-full">
          <div className="flex flex-col items-center text-center">
            <Orbit
              className="w-16 h-16 text-comet-500 opacity-50 mb-4"
              aria-hidden="true"
            />
            <h1 className="text-4xl font-display text-comet-100 mb-2">
              404 — Lost in the void
            </h1>
            <p className="text-sm text-comet-500 mb-6 max-w-sm">
              We can&apos;t find the page you&apos;re looking for. Drift
              back to mission control and we&apos;ll get you oriented.
            </p>
            <Button asChild variant="primary" size="default">
              <Link href="/">Back to dashboard</Link>
            </Button>
          </div>
        </Panel>
      </div>
    </Shell>
  );
}
