import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";
import Tooltip from "@/components/Tooltip";

export const metadata: Metadata = {
  title: "Borsa Research Engine v1.0",
  description: "Quant arastirma sistemi - yatirim tavsiyesi degildir",
};

const navLinks = [
  { href: "/", label: "Ana Sayfa", tip: "Sistem ozeti, takip edilen hisseler ve paper trading durumu" },
  { href: "/weekly-picks", label: "Haftalik Sinyaller", tip: "Modelin bu hafta urettigi alim/satim sinyalleri" },
  { href: "/strategy-lab", label: "Strateji Lab", tip: "Backtest calistir, feature sec, arastirma dongusu baslat" },
  { href: "/model-comparison", label: "Model Karsilastirma", tip: "Farkli modellerin performanslarini karsilastir" },
  { href: "/feature-importance", label: "Feature Onemi", tip: "Hangi feature'lar model tahmininde en etkili" },
  { href: "/risk-warnings", label: "Risk Uyarilari", tip: "Sistem riskleri, kill switch durumu ve uyarilar" },
  { href: "/data-quality", label: "Veri Kalitesi", tip: "Veri eksiklikleri, tutarsizliklar ve kalite skorları" },
  { href: "/data-status", label: "Veri Durumu", tip: "Tum veri kaynaklari, kapsamlari ve sistem durumu" },
  { href: "/backtest", label: "Backtest", tip: "Gecmise donuk strateji testleri ve sonuclari" },
  { href: "/portfolio-simulation", label: "Portfoy Sim", tip: "Strateji bazli sermaye simulasyonu" },
  { href: "/arxiv", label: "ArXiv", tip: "Akademik paper taramasi ve insight kuyrugu" },
  { href: "/ablation", label: "Ablasyon", tip: "Feature group testleri ve oneriler" },
];

const sidebarSections = [
  {
    title: "Ana Menu",
    links: [
      { href: "/", label: "Ana Sayfa", tip: "Sistem ozeti ve paper trading durumu" },
      { href: "/weekly-picks", label: "Haftalik Sinyaller", tip: "Bu haftanin model sinyalleri" },
      { href: "/strategy-lab", label: "Strateji Lab", tip: "Backtest ve arastirma dongusu" },
      { href: "/model-comparison", label: "Model Karsilastirma", tip: "Model performans karsilastirmasi" },
    ],
  },
  {
    title: "Arastirma",
    links: [
      { href: "/feature-importance", label: "Feature Onemi", tip: "Feature etki analizi" },
      { href: "/risk-warnings", label: "Risk Uyarilari", tip: "Risk durumu ve uyarilar" },
      { href: "/data-quality", label: "Veri Kalitesi", tip: "Veri kalite skorları" },
      { href: "/data-status", label: "Veri Durumu", tip: "Veri kaynaklari ve kapsam" },
      { href: "/backtest", label: "Backtest", tip: "Gecmis strateji testleri" },
      { href: "/portfolio-simulation", label: "Portfoy Sim", tip: "Sermaye simulasyonu" },
      { href: "/arxiv", label: "ArXiv", tip: "Paper tarama ve insight kuyruğu" },
      { href: "/ablation", label: "Ablasyon", tip: "Feature group analizi" },
    ],
  },
  {
    title: "Sistem",
    links: [
      { href: "/admin", label: "Admin Panel", tip: "Yonetim paneli" },
      { href: "/admin/jobs", label: "Isler", tip: "Celery is durumlari" },
      { href: "/admin/notifications", label: "Bildirimler", tip: "Sistem bildirimleri" },
      { href: "/stocks", label: "Hisseler", tip: "Tum hisseler listesi" },
    ],
  },
];

const TICKER_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH"];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
        <div className="ticker-bar">
          {TICKER_SYMBOLS.map((symbol) => `${symbol} --% `).join(" | ")}
          &nbsp;&nbsp;VIX: -- &nbsp;|&nbsp; S&amp;P500: -- &nbsp;|&nbsp; Son guncelleme: --
        </div>

        <div
          style={{
            background: "linear-gradient(to bottom, #6699cc, #336699)",
            padding: "6px 12px",
            display: "flex",
            alignItems: "center",
            gap: "12px",
          }}
        >
          <span style={{ color: "#fff", fontWeight: "bold", fontSize: "14px", fontFamily: "Tahoma, sans-serif" }}>
            Borsa Research Engine
          </span>
          <span style={{ color: "#c8d8e8", fontSize: "10px", fontFamily: "Tahoma,sans-serif" }}>v1.0 - Arastirma Sistemi</span>
          <span
            style={{
              marginLeft: "auto",
              color: "#ffffc0",
              fontSize: "10px",
              fontFamily: "Tahoma,sans-serif",
              fontStyle: "italic",
            }}
          >
            Uyari: Yatirim tavsiyesi degildir
          </span>
        </div>

        <div
          style={{
            background: "#d4d0c8",
            borderBottom: "1px solid #808080",
            padding: "2px 6px",
            display: "flex",
            gap: 0,
            flexWrap: "wrap",
          }}
        >
          {navLinks.map((link) => (
            <Tooltip key={link.href} text={link.tip} position="bottom">
              <Link
                href={link.href}
                prefetch={false}
                style={{
                  padding: "2px 10px",
                  fontSize: "11px",
                  fontFamily: "Tahoma,sans-serif",
                  color: "#000",
                  textDecoration: "none",
                  display: "block",
                }}
              >
                {link.label}
              </Link>
            </Tooltip>
          ))}
        </div>

        <div style={{ display: "flex", flex: 1, background: "#fff" }}>
          <div
            style={{
              width: "165px",
              background: "#d4d0c8",
              borderRight: "1px solid #808080",
              flexShrink: 0,
            }}
          >
            {sidebarSections.map((section) => (
              <div key={section.title} style={{ borderBottom: "1px solid #808080" }}>
                <div
                  style={{
                    background: "linear-gradient(to bottom, #6699cc, #336699)",
                    padding: "3px 8px",
                    fontSize: "10px",
                    fontFamily: "Tahoma,sans-serif",
                    fontWeight: "bold",
                    color: "#fff",
                  }}
                >
                  {section.title}
                </div>
                {section.links.map((link) => (
                  <Tooltip key={link.href} text={link.tip || link.label} position="right">
                    <Link
                      href={link.href}
                      prefetch={false}
                      style={{
                        display: "block",
                        padding: "3px 10px",
                        fontSize: "11px",
                        fontFamily: "Tahoma,sans-serif",
                        color: "#00008b",
                        textDecoration: "underline",
                      }}
                    >
                      {link.label}
                    </Link>
                  </Tooltip>
                ))}
              </div>
            ))}

            <div
              style={{
                margin: "6px",
                padding: "6px",
                background: "#ffffc0",
                border: "1px solid #cc9900",
                fontSize: "10px",
                fontFamily: "Tahoma,sans-serif",
              }}
            >
              <b>Sistem Durumu</b>
              <br />
              Pipeline: <span className="text-green">HAZIR</span>
              <br />
              Kill Switch: <span className="text-green">KAPALI</span>
            </div>
          </div>

          <div style={{ flex: 1, padding: "10px", background: "#fff", overflow: "auto" }}>{children}</div>
        </div>

        <div className="status-bar">
          <span className="status-segment">Hazir</span>
          <span className="status-segment">localhost:3000</span>
          <span className="status-segment">20 hisse izleniyor</span>
          <span>Lokal sunucu</span>
        </div>
      </body>
    </html>
  );
}
