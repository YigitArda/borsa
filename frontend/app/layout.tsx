import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Borsa Research Engine v1.0",
  description: "Quant araştırma sistemi — yatırım tavsiyesi değildir",
};

const navLinks = [
  { href: "/", label: "Ana Sayfa" },
  { href: "/weekly-picks", label: "Haftalık Sinyaller" },
  { href: "/strategy-lab", label: "Strateji Lab" },
  { href: "/model-comparison", label: "Model Karşılaştırma" },
  { href: "/feature-importance", label: "Feature Önemi" },
  { href: "/risk-warnings", label: "Risk Uyarıları" },
  { href: "/data-quality", label: "Veri Kalitesi" },
  { href: "/backtest", label: "Backtest" },
];

const sidebarSections = [
  {
    title: "📋 Ana Menü",
    links: [
      { href: "/", label: "🏠 Ana Sayfa" },
      { href: "/weekly-picks", label: "📈 Haftalık Sinyaller" },
      { href: "/strategy-lab", label: "🔬 Strateji Lab" },
      { href: "/model-comparison", label: "📊 Model Karşılaştırma" },
    ],
  },
  {
    title: "🔍 Araştırma",
    links: [
      { href: "/feature-importance", label: "⭐ Feature Önemi" },
      { href: "/risk-warnings", label: "⚠️ Risk Uyarıları" },
      { href: "/data-quality", label: "📋 Veri Kalitesi" },
      { href: "/backtest", label: "🗂️ Backtest" },
    ],
  },
  {
    title: "⚙️ Sistem",
    links: [
      { href: "/admin", label: "👤 Admin Panel" },
      { href: "/admin/jobs", label: "💼 İşler" },
      { href: "/admin/notifications", label: "🔔 Bildirimler" },
      { href: "/stocks", label: "📦 Hisseler" },
    ],
  },
];

const TICKER_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH"];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>

        {/* Ticker scroll */}
        <div className="ticker-bar">
          {TICKER_SYMBOLS.map(s => `${s} --% `).join(" | ")}
          &nbsp;&nbsp;VIX: -- &nbsp;|&nbsp; S&amp;P500: -- &nbsp;|&nbsp; Son güncelleme: --
        </div>

        {/* Topbar */}
        <div style={{
          background: "linear-gradient(to bottom, #6699cc, #336699)",
          padding: "6px 12px", display: "flex", alignItems: "center", gap: "12px"
        }}>
          <span style={{ color: "#fff", fontWeight: "bold", fontSize: "14px", fontFamily: "Tahoma, sans-serif" }}>
            📊 Borsa Research Engine
          </span>
          <span style={{ color: "#c8d8e8", fontSize: "10px", fontFamily: "Tahoma,sans-serif" }}>
            v1.0 — Araştırma Sistemi
          </span>
          <span style={{ marginLeft: "auto", color: "#ffffc0", fontSize: "10px", fontFamily: "Tahoma,sans-serif", fontStyle: "italic" }}>
            ⚠ Yatırım tavsiyesi değildir
          </span>
        </div>

        {/* Menubar */}
        <div style={{
          background: "#d4d0c8", borderBottom: "1px solid #808080",
          padding: "2px 6px", display: "flex", gap: "0"
        }}>
          {navLinks.map(l => (
            <Link key={l.href} href={l.href} style={{
              padding: "2px 10px", fontSize: "11px",
              fontFamily: "Tahoma,sans-serif", color: "#000",
              textDecoration: "none", display: "block"
            }}>
              {l.label}
            </Link>
          ))}
        </div>

        {/* Ana içerik — sidebar + sayfa */}
        <div style={{ display: "flex", flex: 1, background: "#fff" }}>

          {/* Sidebar */}
          <div style={{
            width: "165px", background: "#d4d0c8",
            borderRight: "1px solid #808080", flexShrink: 0
          }}>
            {sidebarSections.map(section => (
              <div key={section.title} style={{ borderBottom: "1px solid #808080" }}>
                <div style={{
                  background: "linear-gradient(to bottom, #6699cc, #336699)",
                  padding: "3px 8px", fontSize: "10px",
                  fontFamily: "Tahoma,sans-serif", fontWeight: "bold", color: "#fff"
                }}>
                  {section.title}
                </div>
                {section.links.map(link => (
                  <Link key={link.href} href={link.href} style={{
                    display: "block", padding: "3px 10px", fontSize: "11px",
                    fontFamily: "Tahoma,sans-serif", color: "#00008b",
                    textDecoration: "underline"
                  }}>
                    {link.label}
                  </Link>
                ))}
              </div>
            ))}

            {/* Sistem durum kutusu */}
            <div style={{
              margin: "6px", padding: "6px", background: "#ffffc0",
              border: "1px solid #cc9900", fontSize: "10px",
              fontFamily: "Tahoma,sans-serif"
            }}>
              <b>⚙ Sistem Durumu</b><br />
              Pipeline: <span className="text-green">HAZIR</span><br />
              Kill Switch: <span className="text-green">KAPALI</span>
            </div>
          </div>

          {/* Sayfa içeriği */}
          <div style={{ flex: 1, padding: "10px", background: "#fff", overflow: "auto" }}>
            {children}
          </div>

        </div>

        {/* Status bar */}
        <div className="status-bar">
          <span className="status-segment">✅ Hazır</span>
          <span className="status-segment">🌐 localhost:3000</span>
          <span className="status-segment">📊 20 hisse izleniyor</span>
          <span>🔒 Lokal sunucu</span>
        </div>

      </body>
    </html>
  );
}
