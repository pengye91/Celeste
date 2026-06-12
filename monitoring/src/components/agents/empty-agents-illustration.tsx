/**
 * Empty-state illustration per spec §6.16 "Agents — no agents":
 * empty docking port / launch pad with a single mooring line.
 *
 * Style: SVG line art, no fills, no gradients, no decorative blobs.
 * Lines use --space-300; a single --aurora-500 accent point sits on
 * the mooring point.
 */
export function EmptyAgentsIllustration() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      role="img"
      aria-label="Empty docking port illustration"
      className="mx-auto"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-space-300"
      >
        {/* Launch pad base (perimeter outline) */}
        <path d="M16 96 L104 96" />
        <path d="M22 96 L22 88 L98 88 L98 96" />
        <path d="M30 88 L30 78" />
        <path d="M90 88 L90 78" />
        <path d="M30 78 L90 78" />

        {/* Docking arms (left/right) */}
        <path d="M30 78 L20 64" />
        <path d="M90 78 L100 64" />
        <path d="M20 64 L20 56" />
        <path d="M100 64 L100 56" />
        <path d="M20 56 L100 56" />

        {/* Center mooring mast */}
        <path d="M60 56 L60 22" />
        {/* Crossbar */}
        <path d="M48 32 L72 32" />
        {/* Anchor tip (top) */}
        <path d="M60 22 L56 18 M60 22 L64 18" />

        {/* Mooring line from center down to pad */}
        <path d="M60 56 L60 70" />
        <path d="M54 70 L66 70" />
        <path d="M57 70 L57 78" />
        <path d="M63 70 L63 78" />

        {/* Footprint markers on pad */}
        <path d="M40 92 L48 92" />
        <path d="M72 92 L80 92" />
      </g>

      {/* Single aurora accent: the mooring point glow */}
      <circle
        cx="60"
        cy="70"
        r="2"
        className="fill-aurora-500 motion-safe:animate-pulse-glow"
      />
    </svg>
  );
}
