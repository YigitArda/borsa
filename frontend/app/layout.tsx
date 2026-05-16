import Link from "next/link";
import type { Metadata } from "next";
import Tooltip from "@/components/Tooltip";

export const metadata: Metadata = {
  title: "Borsa Research Engine v1.0",
  description: "Quant arastirma sistemi - yatirim tavsiyesi degildir",
};

const navLinks = [
  { href: "/", label: "Ana Sayfa", tip: "Genel bakis: sinyaller, hisseler ve sistem durumu" },
  { href: "/weekly-picks", label: "Bu Haftanin Sinyalleri", tip: "Modelin bu hafta onerilen hisseleri ve tahminleri" },
  { href: "/stocks", label: "Hisseler", tip: "Takip edilen tum hisselerin listesi ve detaylari" },
  { href: "/strategy-lab", label: "Strateji Laboratuvari", tip: "Yeni strateji dene, gecmis test et, model egit" },
  { href: "/backtest", label: "Gecmis Test Sonuclari", tip: "Yapilan tum backtest ve strateji gecmis performanslari" },
  { href: "/portfolio-simulation", label: "Portfoy Simulasyonu", tip: "Sermaye dagitimi ve portfoy performans simulasyonu" },
  { href: "/risk-warnings", label: "Risk Uyarilari", tip: "Sistem riskleri, durdurma kosullari ve uyarilar" },
  { href: "/data-quality", label: "Veri Kalitesi", tip: "Veri eksiklikleri ve guvenirligi" },
  { href: "/model-comparison", label: "Model Karsilastirma", tip: "Farkli modellerin performans karsilastirmasi" },
  { href: "/feature-importance", label: "Hangi Faktorler Etkili?", tip: "Modelin en cok hangi verilere baktigini goster" },
  { href: "/trinity-screener", label: "Hisse Taramasi", tip: "Deger+Kalite+Momentum kriterleriyle hisse tara" },
  { href: "/research/regime", label: "Piyasa Ortami Analizi", tip: "Dusuk/orta/yuksek volatilite donemlerinde strateji performansi" },
  { href: "/research/calibration", label: "Tahmin Guvenilirligi", tip: "Model tahminlerinin gerceklesmeyle ne kadar uyustugu" },
  { href: "/ablation", label: "Faktor Etki Analizi", tip: "Hangi faktor olmadan model daha iyi/kotu calisiyor" },
  { href: "/arxiv", label: "Akademik Arastirmalar", tip: "Guncel finans arastirma makaleleri ve icgoru kuyrugu" },
  { href: "/hypotheses", label: "Arastirma Hipotezleri", tip: "Test edilecek ve izlenecek yatirim hipotezleri" },
];

const sidebarSections = [
  {
    title: "Baslangiç",
    links: [
      { href: "/", label: "Genel Bakis", tip: "Sistemin durumu ve ozeti" },
      { href: "/weekly-picks", label: "Bu Haftanin Sinyalleri", tip: "Model bu hafta hangi hisseleri oneriyor?" },
      { href: "/stocks", label: "Hisseler Listesi", tip: "Takip edilen tum hisseler" },
      { href: "/risk-warnings", label: "Risk & Uyarilar", tip: "Sistem riskleri ve durdurma kosullari" },
    ],
  },
  {
    title: "Strateji & Test",
    links: [
      { href: "/strategy-lab", label: "Strateji Laboratuvari", tip: "Yeni strateji dene, gecmis test et" },
      { href: "/backtest", label: "Gecmis Test Sonuclari", tip: "Tum backtest gecmisi" },
      { href: "/portfolio-simulation", label: "Portfoy Simulasyonu", tip: "Sermaye dagitim simulasyonu" },
      { href: "/model-comparison", label: "Model Karsilastirma", tip: "Modelleri yan yana karsilastir" },
    ],
  },
  {
    title: "Analiz",
    links: [
      { href: "/feature-importance", label: "Hangi Faktorler Etkili?", tip: "Model hangi verilere bakiyor?" },
      { href: "/trinity-screener", label: "Hisse Taramasi", tip: "Deger+Kalite+Momentum tarama" },
      { href: "/research/regime", label: "Piyasa Ortami", tip: "Volatilite donemlerine gore performans" },
      { href: "/research/calibration", label: "Tahmin Guvenilirligi", tip: "Tahminler gerceklesmeyle uyusuyor mu?" },
      { href: "/ablation", label: "Faktor Etki Analizi", tip: "Hangi faktor modeli ne kadar etkiliyor?" },
    ],
  },
  {
    title: "Veri & Sistem",
    links: [
      { href: "/data-quality", label: "Veri Kalitesi", tip: "Veri eksiklikleri ve tutarsizliklar" },
      { href: "/data-status", label: "Veri Kaynaklari", tip: "Tum veri kaynaklari ve kapsam" },
      { href: "/arxiv", label: "Arastirma Makaleleri", tip: "Guncel finans arastirmalari" },
      { href: "/hypotheses", label: "Arastirma Hipotezleri", tip: "Test edilecek hipotezler" },
      { href: "/admin", label: "Sistem Yonetimi", tip: "Admin paneli ve job takibi" },
    ],
  },
];

const TICKER_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH"];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <head>
        <link rel="stylesheet" href="/retro.css" />
      </head>
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

            <div className="guide-box">
              <b>Nasil Kullanilir?</b>
              <br />
              1. <a href="/weekly-picks">Sinyallere</a> bak
              <br />
              2. <a href="/stocks">Hisse</a> arastir
              <br />
              3. <a href="/strategy-lab">Strateji</a> test et
              <br />
              4. <a href="/risk-warnings">Riskleri</a> takip et
            </div>
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
              <b>Sistem</b>
              <br />
              Pipeline: <span className="text-green">HAZIR</span>
              <br />
              Her Cumartesi guncellenir
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
