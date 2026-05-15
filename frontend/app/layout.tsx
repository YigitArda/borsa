import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";
import Tooltip from "@/components/Tooltip";

export const metadata: Metadata = {
  title: "Borsa Research Engine v1.0",
  description: "Quant araştırma sistemi — yatırım tavsiyesi değildir",
};

const navLinks = [
  { href: "/", label: "Ana Sayfa", tip: "Sistem özeti, takip edilen hisseler ve paper trading durumu" },
  { href: "/weekly-picks", label: "Haftalık Sinyaller", tip: "Modelin bu hafta için ürettiği alım/satım sinyalleri" },
  { href: "/strategy-lab", label: "Strateji Lab", tip: "Backtest çalıştır, feature seç, araştırma döngüsü başlat" },
  { href: "/model-comparison", label: "Model Karşılaştırma", tip: "Farklı modellerin performanslarını karşılaştır" },
  { href: "/feature-importance", label: "Feature Önemi", tip: "Hangi feature'lar model tahmininde en etkili" },
  { href: "/risk-warnings", label: "Risk Uyarıları", tip: "Sistem riskleri, kill switch durumu ve uyarılar" },
  { href: "/data-quality", label: "Veri Kalitesi", tip: "Veri eksiklikleri, tutarsızlıklar ve kalite skorları" },
  { href: "/data-status", label: "Veri Durumu", tip: "Tüm veri kaynakları, kapsamları ve sistem durumu" },
  { href: "/backtest", label: "Backtest", tip: "Geçmişe dönük strateji testleri ve sonuçları" },
];

const sidebarSections = [
  {
    title: "📋 Ana Menü",
    links: [
      { href: "/", label: "🏠 Ana Sayfa", tip: "Sistem özeti ve paper trading durumu" },
      { href: "/weekly-picks", label: "📈 Haftalık Sinyaller", tip: "Bu haftanın model sinyalleri" },
      { href: "/strategy-lab", label: "🔬 Strateji Lab", tip: "Backtest ve araştırma döngüsü" },
      { href: "/model-comparison", label: "📊 Model Karşılaştırma", tip: "Model performans karşılaştırması" },
    ],
  },
  {
    title: "🔍 Araştırma",
    links: [
      { href: "/feature-importance", label: "⭐ Feature Önemi", tip: "Feature etki analizi" },
      { href: "/risk-warnings", label: "⚠️ Risk Uyarıları", tip: "Risk durumu ve uyarılar" },
      { href: "/data-quality", label: "📋 Veri Kalitesi", tip: "Veri kalite skorları" },
      { href: "/data-status", label: "📊 Veri Durumu", tip: "Veri kaynakları ve kapsam" },
      { href: "/backtest", label: "🗂️ Backtest", tip: "Geçmiş strateji testleri" },
    ],
  },
  {
    title: "⚙️ Sistem",
    links: [
      { href: "/admin", label: "👤 Admin Panel", tip: "Yönetim paneli" },
      { href: "/admin/jobs", label: "💼 İşler", tip: "Celery iş durumları" },
      { href: "/admin/notifications", label: "🔔 Bildirimler", tip: "Sistem bildirimleri" },
      { href: "/stocks", label: "📦 Hisseler", tip: "Tüm hisseler listesi" },
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
            <Tooltip key={l.href} text={l.tip} position="bottom">
              <Link href={l.href} prefetch={false} style={{
                padding: "2px 10px", fontSize: "11px",
                fontFamily: "Tahoma,sans-serif", color: "#000",
                textDecoration: "none", display: "block"
              }}>
                {l.label}
              </Link>
            </Tooltip>
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
                  <Tooltip key={link.href} text={link.tip || link.label} position="right">
                    <Link href={link.href} prefetch={false} style={{
                      display: "block", padding: "3px 10px", fontSize: "11px",
                      fontFamily: "Tahoma,sans-serif", color: "#00008b",
                      textDecoration: "underline"
                    }}>
                      {link.label}
                    </Link>
                  </Tooltip>
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
