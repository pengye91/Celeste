import type { Metadata } from "next";
import { Bodoni_Moda, Syne, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "./animations.css";
import { QueryClientProviderWrapper } from "@/components/providers/query-client-provider";
import { Toaster } from "@/components/ui/toast";

const bodoni = Bodoni_Moda({
  variable: "--font-bodoni",
  subsets: ["latin"],
  display: "swap",
});

const syne = Syne({
  variable: "--font-syne",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Celeste Mission Control",
  description: "Workflow monitoring and observability dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${bodoni.variable} ${syne.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-space-void text-space-100">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-tooltip focus:px-3 focus:py-2 focus:rounded-md focus:bg-aurora-500 focus:text-space-void focus:font-mono focus:text-xs focus:shadow-glow focus:outline-none focus:ring-2 focus:ring-aurora-300"
        >
          Skip to main content
        </a>
        <QueryClientProviderWrapper>
          {children}
          <Toaster />
        </QueryClientProviderWrapper>
      </body>
    </html>
  );
}
