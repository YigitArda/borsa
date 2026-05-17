import { loadApi } from "@/lib/server-api";
import Link from "next/link";

type DataConnector = {
  provider_id: string;
  name: string;
  category: string;
  enabled: boolean;
  configured: boolean;
  requires_api_key: boolean;
  priority: number;
  last_status: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_message: string | null;
  coverage_score: number | null;
  freshness_score: number | null;
  quality_score: number | null;
};

type HealthSummary = {
  total: number;
  enabled: number;
  configured: number;
  ok: number;
  failed: number;
  skipped: number;
  connectors: DataConnector[];
};

const CATEGORY_LABELS: Record<string, string> = {
  NEWS: "Haber",
  PRICES: "Fiyat",
  MACRO: "Makro",
  CRYPTO: "Kripto",
  SENTIMENT: "Sosyal Medya",
  GOVERNMENT: "Hükümet",
  ALTERNATIVE: "Alternatif",
};

const CATEGORY_DESC: Record<string, string> = {
  NEWS: "Haber makaleleri ve şirket duyuruları",
  PRICES: "Hisse senedi OHLCV fiyat verisi",
  MACRO: "Faiz, enflasyon, büyüme gibi makroekonomik göstergeler",
  CRYPTO: "Bitcoin, Ethereum kripto fiyat verisi",
  SENTIMENT: "Reddit, Twitter, StockTwits sosyal medya sinyalleri",
  GOVERNMENT: "ABD federal hükümet kontratları",
  ALTERNATIVE: "Alternatif piyasa verileri (Çin, HK)",
};

function statusBadge(status: string | null, configured: boolean, enabled: boolean) {
  if (!enabled) return { cls: "badge-info", label: "DEVRE DISI" };
  if (!configured) return { cls: "badge-warning", label: "API KEY YOK" };
  if (status === "ok") return { cls: "badge-success", label: "CALISYOR" };
  if (status === "partial") return { cls: "badge-warning", label: "KISMI" };
  if (status === "skipped") return { cls: "badge-info", label: "ATLANDI" };
  if (status === "failed") return { cls: "badge-danger", label: "HATA" };
  return { cls: "badge-info", label: "BEKLIYOR" };
}

function score(v: number | null) {
  if (v == null) return "—";
  const pct = Math.round(v * 100);
  const color = pct >= 80 ? "#006600" : pct >= 50 ? "#886600" : "#cc0000";
  return <span style={{ color, fontWeight: "bold" }}>{pct}%</span>;
}

function timeAgo(iso: string | null) {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d} gün önce`;
  if (h > 0) return `${h} saat önce`;
  return "Az önce";
}

export default async function DataSourcesPage() {
  const healthResult = await loadApi<HealthSummary>("/data-sources/health");
  const listResult = await loadApi<DataConnector[]>("/data-sources");

  const health = healthResult.data;
  const connectors: DataConnector[] = listResult.data ?? health?.connectors ?? [];

  const byCategory: Record<string, DataConnector[]> = {};
  for (const c of connectors) {
    const cat = c.category || "OTHER";
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(c);
  }

  const categoryOrder = ["PRICES", "NEWS", "MACRO", "SENTIMENT", "GOVERNMENT", "CRYPTO", "ALTERNATIVE"];
  const sortedCategories = [
    ...categoryOrder.filter((c) => byCategory[c]),
    ...Object.keys(byCategory).filter((c) => !categoryOrder.includes(c)),
  ];

  const total = connectors.length;
  const configured = connectors.filter((c) => c.configured).length;
  const ok = connectors.filter((c) => c.last_status === "ok").length;
  const failed = connectors.filter((c) => c.last_status === "failed").length;
  const needsKey = connectors.filter((c) => c.requires_api_key && !c.configured).length;

  return (
    <div>
      <h1>Veri Kaynaklari ve Connector Durumu</h1>

      <div className="info-box" style={{ marginBottom: "12px" }}>
        <b>Bu sayfa ne gosteriyor?</b> — Sistemin veri cekebilecegi tum kaynaklar ve bunlarin anlık durumu
        listelenir. "API Key Yok" gorunen connectorlar icin <code>.env</code> dosyasına ilgili key eklenince
        otomatik aktif hale gelir. Connector calistirma icin{" "}
        <Link href="/strategy-lab">Strateji Laboratuvari</Link> &gt; Pipeline adımını kullanın.
      </div>

      {/* Özet metrik kartlar */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "8px", marginBottom: "12px" }}>
        <div className="metric-card">
          <div className="metric-label">Toplam Connector</div>
          <div className="metric-value">{total}</div>
          <div className="metric-sub">kayitli provider</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Yapilandirilmis</div>
          <div className="metric-value" style={{ color: configured > 0 ? "#006600" : "#666" }}>{configured}</div>
          <div className="metric-sub">hazir ve aktif</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Son Calistirma OK</div>
          <div className="metric-value" style={{ color: ok > 0 ? "#006600" : "#666" }}>{ok}</div>
          <div className="metric-sub">basarili provider</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Hata</div>
          <div className="metric-value" style={{ color: failed > 0 ? "#cc0000" : "#666" }}>{failed}</div>
          <div className="metric-sub">son calistirmada</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">API Key Bekliyor</div>
          <div className="metric-value" style={{ color: needsKey > 0 ? "#886600" : "#006600" }}>{needsKey}</div>
          <div className="metric-sub">.env ile aktif edilir</div>
        </div>
      </div>

      {needsKey > 0 && (
        <div className="alert alert-warning" style={{ marginBottom: "12px" }}>
          <b>{needsKey} connector API key bekliyor.</b> Polygon, FRED veya Twitter gibi kaynaklar .env dosyasına
          ilgili key eklendikten sonra otomatik aktif hale gelir. Ücretsiz kaynaklar (WorldBank, IMF, Kraken,
          GDELT, SEC, RSS) ise hemen kullanılabilir durumda.
        </div>
      )}

      {connectors.length === 0 && (
        <div className="alert alert-warning">
          <b>Connector listesi alınamadı.</b> Backend çalışıyor mu?{" "}
          <code>POST /data-sources/sync</code> endpoint'i ile registry senkronize edilmeli.
        </div>
      )}

      {/* Kategori bazlı connector tabloları */}
      {sortedCategories.map((cat) => (
        <div key={cat} className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">
            {CATEGORY_LABELS[cat] ?? cat} Connectorlari
            <span style={{ fontWeight: "normal", marginLeft: "8px", fontSize: "10px" }}>
              — {CATEGORY_DESC[cat] ?? ""}
            </span>
          </div>
          <div className="box-body" style={{ padding: 0 }}>
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Durum</th>
                  <th title="API key gerekiyor mu?">API Key</th>
                  <th title="Son basarili calistirma zamani">Son Basari</th>
                  <th title="Veri kalite skoru (0-100)">Kalite</th>
                  <th title="Veri tazelik skoru (0-100)">Tazelik</th>
                  <th title="Son mesaj veya hata">Mesaj</th>
                </tr>
              </thead>
              <tbody>
                {byCategory[cat].sort((a, b) => a.priority - b.priority).map((c) => {
                  const badge = statusBadge(c.last_status, c.configured, c.enabled);
                  return (
                    <tr key={c.provider_id}>
                      <td>
                        <b style={{ fontFamily: "monospace", fontSize: "11px" }}>{c.provider_id}</b>
                        <div style={{ fontSize: "10px", color: "#666" }}>{c.name}</div>
                      </td>
                      <td>
                        <span className={`badge ${badge.cls}`}>{badge.label}</span>
                      </td>
                      <td>
                        {c.requires_api_key ? (
                          c.configured ? (
                            <span className="text-green">✓ Var</span>
                          ) : (
                            <span className="text-red">✗ Eksik</span>
                          )
                        ) : (
                          <span className="text-muted">Gerekmez</span>
                        )}
                      </td>
                      <td style={{ fontSize: "10px", color: "#666" }}>{timeAgo(c.last_success_at)}</td>
                      <td>{score(c.quality_score)}</td>
                      <td>{score(c.freshness_score)}</td>
                      <td style={{ fontSize: "10px", color: c.last_status === "failed" ? "#cc0000" : "#666", maxWidth: "200px" }}>
                        {c.last_message ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {/* API Key rehberi */}
      {needsKey > 0 && (
        <div className="box" style={{ marginBottom: "12px" }}>
          <div className="box-head">Eksik API Key'ler — .env Dosyasına Ekle</div>
          <div className="box-body">
            <table className="data-table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>.env Degiskeni</th>
                  <th>Nasil Alinir</th>
                  <th>Ucretli mi?</th>
                </tr>
              </thead>
              <tbody>
                {connectors.filter((c) => c.requires_api_key && !c.configured).map((c) => (
                  <tr key={c.provider_id}>
                    <td><b>{c.name}</b></td>
                    <td><code style={{ fontSize: "10px" }}>{c.provider_id.toUpperCase().replace(/_/g, "")}_API_KEY</code></td>
                    <td style={{ fontSize: "10px", color: "#336699" }}>
                      {c.provider_id.startsWith("polygon") && "polygon.io → Free tier mevcut"}
                      {c.provider_id.startsWith("fred") && "fred.stlouisfed.org → Ucretsiz"}
                      {c.provider_id.startsWith("adanos") && "Adanos dokumantasyonuna bakin"}
                      {!c.provider_id.startsWith("polygon") && !c.provider_id.startsWith("fred") && !c.provider_id.startsWith("adanos") && "Provider dokumantasyonuna bakin"}
                    </td>
                    <td style={{ fontSize: "10px" }}>
                      {c.provider_id.startsWith("fred") && <span className="text-green">Hayir (ucretsiz)</span>}
                      {c.provider_id.startsWith("polygon") && <span style={{ color: "#886600" }}>Free tier var</span>}
                      {c.provider_id.startsWith("adanos") && <span style={{ color: "#886600" }}>Ucretli</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div style={{
        textAlign: "center", padding: "6px", background: "#e8f0f8",
        border: "1px solid #c0c0c0", fontSize: "10px", color: "#666", marginTop: "8px",
      }}>
        Connector calistirmak icin:{" "}
        <code>POST /data-sources/run</code> veya{" "}
        <Link href="/strategy-lab">Strateji Laboratuvari &raquo;</Link>
      </div>
    </div>
  );
}
