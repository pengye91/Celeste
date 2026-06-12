export const colors = {
  space: {
    void: "#050508",
    900: "#0a0a0f",
    800: "#0f0f16",
    700: "#14141e",
    600: "#1a1a26",
    500: "#222233",
    400: "#2d2d44",
    300: "#3d3d5c",
    200: "#555580",
    100: "#7a7aa8",
    50: "#a8a8cc",
  },
  aurora: {
    500: "#00d4aa",
    400: "#33e0bf",
    300: "#66ebd4",
    200: "#99f5e8",
    100: "#ccfaf3",
    50: "#e5fdf8",
  },
  solar: {
    500: "#f5a623",
    400: "#f7b84e",
    300: "#f9ca7a",
    200: "#fbdba6",
    100: "#fdedd2",
    50: "#fef6e9",
  },
  mars: {
    500: "#e8453c",
    400: "#ed6a63",
    300: "#f28f8a",
    200: "#f7b4b1",
    100: "#fcd9d8",
    50: "#fdecec",
  },
  nebula: {
    500: "#6b5ce7",
    400: "#8a7eec",
    300: "#a9a0f1",
    200: "#c8c3f6",
    100: "#e3e0fa",
    50: "#f1f0fd",
  },
  comet: {
    500: "#8a8a9e",
    400: "#a0a0b0",
    300: "#b6b6c2",
    200: "#ccccd4",
    100: "#e2e2e6",
    50: "#f0f0f2",
  },
} as const;

export function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
