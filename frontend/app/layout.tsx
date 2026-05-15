import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Borsa Research Engine",
  description: "Self-improving stock strategy research — not financial advice",
};

const navLinks = [
  { href: "/", label: "Dashboard" },
  { href: "/weekly-picks", label: "Weekly Picks" },
  { href: "/strategy-lab", label: "Strategy Lab" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <nav className="border-b border-slate-700 bg-slate-900 px-6 py-3 flex items-center gap-8">
          <span className="text-lg font-bold text-blue-400">Borsa</span>
          {navLinks.map((l) => (
            <Link key={l.href} href={l.href} className="text-sm text-slate-300 hover:text-white transition-colors">
              {l.label}
            </Link>
          ))}
          <span className="ml-auto text-xs text-slate-500 italic">Not financial advice</span>
        </nav>
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}
