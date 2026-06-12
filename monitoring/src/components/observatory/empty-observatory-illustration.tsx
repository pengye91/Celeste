/**
 * Empty Observatory illustration.
 *
 * A line-art telescope-dish concept rendered as a 120x120 SVG. Uses
 * design tokens directly via CSS variable references so the illustration
 * follows the rest of the design system. This is intentionally
 * monochrome with a single accent dot — it should feel like a quiet
 * observing instrument, not a notification.
 */
export function EmptyObservatoryIllustration({
  className,
}: {
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 120 120"
      width={120}
      height={120}
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Empty observatory illustration"
      className={className}
    >
      <title>Empty observatory</title>
      {/* Outer dish rim */}
      <circle
        cx="60"
        cy="56"
        r="38"
        fill="none"
        stroke="var(--space-300)"
        strokeWidth="1.5"
      />
      {/* Inner dish curve */}
      <path
        d="M30 56 Q60 32 90 56"
        fill="none"
        stroke="var(--space-300)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <path
        d="M30 56 Q60 80 90 56"
        fill="none"
        stroke="var(--space-300)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      {/* Stand */}
      <line
        x1="60"
        y1="94"
        x2="60"
        y2="108"
        stroke="var(--space-300)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <line
        x1="48"
        y1="108"
        x2="72"
        y2="108"
        stroke="var(--space-300)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      {/* Accent — a single signal dot in the dish */}
      <circle
        cx="60"
        cy="56"
        r="3"
        fill="var(--aurora-500)"
      />
      {/* Faint scan rays */}
      <line
        x1="60"
        y1="18"
        x2="60"
        y2="10"
        stroke="var(--aurora-500)"
        strokeWidth="1.25"
        strokeLinecap="round"
        opacity="0.6"
      />
      <line
        x1="92"
        y1="36"
        x2="98"
        y2="30"
        stroke="var(--aurora-500)"
        strokeWidth="1.25"
        strokeLinecap="round"
        opacity="0.4"
      />
      <line
        x1="28"
        y1="36"
        x2="22"
        y2="30"
        stroke="var(--aurora-500)"
        strokeWidth="1.25"
        strokeLinecap="round"
        opacity="0.4"
      />
    </svg>
  );
}
