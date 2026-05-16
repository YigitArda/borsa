import type { ReactNode } from "react";
import { loadApi } from "@/lib/server-api";

type DataSourceRow = {
  name: string;
  source: string;
  period: string;
  range: string;
  totalRecords: string;
  coverage: string;
  status: string;
};

type CoverageRow = {
  ticker: string;
  weeks: number;
  years: number;
  start: string | null;
  end: string | null;
};

type FeatureCategoryRow = {
  category: string;
  count: number;
  examples: string;
};

type StatusRow = {
  name: string;
  status: string;
  detail: string;
};

type DataQualityReport = {
  stocks: Array<{
    ticker: string;
    name: string;
    weekly_price_rows: number;
    daily_price_rows: number;
    feature_rows: number;
    latest_week: string | null;
    status: string;
  }>;
  macro_freshness: Record<string, string>;
  data_quality_gates: {
    pit_financial_rows: number;
    yfinance_financial_rows: number;
    universe_snapshot_count: number;
    ticker_alias_count: number;
    corporate_action_count: number;
    warnings: string[];
  };
  total_stocks: number;
  stocks_with_data: number;
};

type DataStatusSummary = {
  generated_at: string;
  stock_count: number;
  price_coverage: {
    total_rows: number;
    covered_stocks: number;
    range_start: string | null;
    range_end: string | null;
    details: CoverageRow[];
  };
  feature_coverage: {
    total_rows: number;
    distinct_features: number;
    categories: FeatureCategoryRow[];
  };
  label_coverage: {
    total_rows: number;
    distinct_targets: number;
    range_start: string | null;
    range_end: string | null;
  };
  data_sources: DataSourceRow[];
  system_status: StatusRow[];
};

function statusBadge(status: string) {
  if (status === "Aktif" || status === "ok") return "badge-success";
  if (status === "Kismi" || status === "partial" || status === "warning") return "badge-warning";
  if (status === "Pasif" || status === "error") return "badge-danger";
  return "badge-info";
}

export default async function DataStatusPage() {
  const summaryResult = await loadApi<DataStatusSummary>("/data-quality/summary");
  const reportResult = summaryResult.data ? null : await loadApi<DataQualityReport>("/data-quality");
  const summary = summaryResult.data;
  const report = reportResult?.data;
  const compatibilityMode = !summary && !!report;
  const generatedAt = summary ? new Date(summary.generated_at).toLocaleString("tr-TR") : null;

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
      <h1>Veri Durumu Raporu</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Sistem veri kaynaklari, kapsam ve calisma durumu tek bir backend ozetinden okunur.
      </p>

      {compatibilityMode && (
        <div className="alert alert-warning">
          Backend bu ortamda <code>/data-quality/summary</code> endpointini sunmuyor. Uyumluluk modu olarak{" "}
          <code>/data-quality</code> raporu gosteriliyor.
        </div>
      )}

      {summaryResult.error && !report && (
        <div className="alert alert-danger">Veri ozeti yuklenemedi: {summaryResult.error}</div>
      )}

      {summary ? (
        <>
          <StatGrid
            items={[
              { label: "Aktif Hisse", value: summary.stock_count },
              { label: "Fiyat Kayitlari", value: summary.price_coverage.total_rows },
              { label: "Feature Kayitlari", value: summary.feature_coverage.total_rows },
              { label: "Label Kayitlari", value: summary.label_coverage.total_rows },
              { label: "Veri Kaynagi", value: summary.data_sources.length },
            ]}
          />

          <InfoStrip
            leftLabel="Son guncelleme"
            leftValue={generatedAt ?? "Bilinmiyor"}
            middleLabel="Fiyat araligi"
            middleValue={`${summary.price_coverage.range_start ?? "N/A"} - ${summary.price_coverage.range_end ?? "N/A"}`}
            rightLabel="Feature aileleri"
            rightValue={summary.feature_coverage.categories.length.toString()}
          />

          <Section title="Veri Kaynaklari ve Durumlari">
            <DataTable
              headers={["Veri Tipi", "Kaynak", "Periyot", "Tarih Araligi", "Toplam Kayit", "Kapsam", "Durum"]}
              rows={summary.data_sources.map((row) => [
                <strong key={`${row.name}-name`}>{row.name}</strong>,
                row.source,
                row.period,
                <span key={`${row.name}-range`} style={{ fontFamily: "monospace", fontSize: "10px" }}>{row.range}</span>,
                row.totalRecords,
                row.coverage,
                <Badge key={`${row.name}-status`} status={row.status}>{row.status.toUpperCase()}</Badge>,
              ])}
            />
          </Section>

          <Section title="Hisse Bazli Fiyat Verisi">
            <DataTable
              headers={["#", "Ticker", "Hafta", "Yil", "Baslangic", "Bitis"]}
              rows={summary.price_coverage.details.map((row, index) => [
                index + 1,
                <strong key={`${row.ticker}-ticker`}>{row.ticker}</strong>,
                row.weeks.toLocaleString(),
                row.years.toFixed(1),
                row.start ?? "N/A",
                row.end ?? "N/A",
              ])}
            />
          </Section>

          <Section title="Feature Kategorileri">
            <DataTable
              headers={["Kategori", "Sayi", "Ornekler"]}
              rows={summary.feature_coverage.categories.map((row) => [
                <strong key={`${row.category}-category`}>{row.category}</strong>,
                row.count,
                row.examples,
              ])}
            />
          </Section>

          <Section title="Sistem Durumu">
            <DataTable
              headers={["Bilesen", "Durum", "Detay"]}
              rows={summary.system_status.map((row) => [
                <strong key={`${row.name}-name`}>{row.name}</strong>,
                <Badge key={`${row.name}-status`} status={row.status}>{row.status.toUpperCase()}</Badge>,
                row.detail,
              ])}
            />
          </Section>
        </>
      ) : report ? (
        <>
          <StatGrid
            items={[
              { label: "Toplam Hisse", value: report.total_stocks },
              { label: "Verisi Olan Hisse", value: report.stocks_with_data },
              { label: "Eksik Hisse", value: Math.max(report.total_stocks - report.stocks_with_data, 0) },
              { label: "Makro Gosterge", value: Object.keys(report.macro_freshness).length },
              { label: "Uyari Sayisi", value: report.data_quality_gates.warnings.length },
            ]}
          />

          <InfoStrip
            leftLabel="Uyumluluk modu"
            leftValue="Legacy /data-quality report"
            middleLabel="Hisse kapsama orani"
            middleValue={
              report.total_stocks > 0
                ? `${Math.round((report.stocks_with_data / report.total_stocks) * 100)}%`
                : "N/A"
            }
            rightLabel="Makro seri sayisi"
            rightValue={Object.keys(report.macro_freshness).length.toString()}
          />

          <Section title="Makro Veri Tazeligi">
            <DataTable
              headers={["Gostergeler", "Son Guncelleme"]}
              rows={Object.entries(report.macro_freshness).map(([code, value]) => [
                <strong key={`${code}-name`}>{code}</strong>,
                <span key={`${code}-value`} style={{ fontFamily: "monospace", fontSize: "10px" }}>{value}</span>,
              ])}
            />
          </Section>

          <Section title="Veri Kalitesi Kapilari">
            <DataTable
              headers={["Bilesen", "Deger"]}
              rows={[
                ["PIT finansal kayitlari", report.data_quality_gates.pit_financial_rows.toLocaleString()],
                ["yfinance finansal kayitlari", report.data_quality_gates.yfinance_financial_rows.toLocaleString()],
                ["Universe snapshot sayisi", report.data_quality_gates.universe_snapshot_count.toLocaleString()],
                ["Ticker alias sayisi", report.data_quality_gates.ticker_alias_count.toLocaleString()],
                ["Corporate action sayisi", report.data_quality_gates.corporate_action_count.toLocaleString()],
              ].map(([label, value]) => [
                <strong key={`${label}-name`}>{label}</strong>,
                value,
              ])}
            />
            <div style={{ borderTop: "1px solid #c0c0c0", padding: "8px" }}>
              <div className="section-label">Uyarilar</div>
              {report.data_quality_gates.warnings.length > 0 ? (
                <ul style={{ paddingLeft: "18px", lineHeight: 1.6 }}>
                  {report.data_quality_gates.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              ) : (
                <div className="text-muted">Uyari yok.</div>
              )}
            </div>
          </Section>

          <Section title="Hisse Bazli Veri Durumu">
            <DataTable
              headers={["Ticker", "Gunluk", "Haftalik", "Feature", "Son Hafta", "Durum"]}
              rows={report.stocks.map((row) => [
                <strong key={`${row.ticker}-ticker`}>{row.ticker}</strong>,
                row.daily_price_rows.toLocaleString(),
                row.weekly_price_rows.toLocaleString(),
                row.feature_rows.toLocaleString(),
                row.latest_week ?? "—",
                <Badge key={`${row.ticker}-status`} status={reportStockBadgeStatus(row.status)}>
                  {reportStockLabel(row.status)}
                </Badge>,
              ])}
            />
          </Section>
        </>
      ) : (
        <div className="alert alert-danger">
          Veri ozeti su anda alinmadi. Backend tekrar cevrimici oldugunda bu sayfa otomatik olarak guncellenecek.
        </div>
      )}

      <div className="alert alert-info" style={{ marginTop: "12px", textAlign: "center", fontSize: "10px" }}>
        Bu sistem yalnizca arastirma amaclidir, yatirim tavsiyesi degildir.
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="box" style={{ marginTop: "12px" }}>
      <div className="box-head">{title}</div>
      <div className="box-body" style={{ padding: 0, overflowX: "auto" }}>
        {children}
      </div>
    </section>
  );
}

function DataTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: ReactNode[][];
}) {
  return (
    <table className="data-table" style={{ marginBottom: 0 }}>
      <thead>
        <tr>
          {headers.map((header) => (
            <th key={header}>{header}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={headers.length} style={{ color: "#666" }}>
              Veri bulunamadi.
            </td>
          </tr>
        ) : (
          rows.map((cells, rowIndex) => (
            <tr key={rowIndex}>
              {cells.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function StatGrid({ items }: { items: Array<{ label: string; value: number | string }> }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: "8px" }}>
      {items.map((item) => (
        <StatCard key={item.label} label={item.label} value={item.value} />
      ))}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="box" style={{ marginBottom: 0 }}>
      <div className="box-head">{label}</div>
      <div className="box-body">
        <div style={{ fontSize: "20px", fontWeight: "bold" }}>
          {typeof value === "number" ? value.toLocaleString() : value}
        </div>
      </div>
    </div>
  );
}

function InfoStrip({
  leftLabel,
  leftValue,
  middleLabel,
  middleValue,
  rightLabel,
  rightValue,
}: {
  leftLabel: string;
  leftValue: string;
  middleLabel: string;
  middleValue: string;
  rightLabel: string;
  rightValue: string;
}) {
  return (
    <div className="box" style={{ marginTop: "12px" }}>
      <div className="box-body">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "12px" }}>
          <StripItem label={leftLabel} value={leftValue} />
          <StripItem label={middleLabel} value={middleValue} />
          <StripItem label={rightLabel} value={rightValue} />
        </div>
      </div>
    </div>
  );
}

function StripItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="section-label">{label}</div>
      <div style={{ color: "#000", fontWeight: "bold" }}>{value}</div>
    </div>
  );
}

function reportStockLabel(status: string) {
  if (status === "ok") return "TAMAM";
  if (status === "insufficient_data") return "EKSIK";
  return status.toUpperCase();
}

function reportStockBadgeStatus(status: string) {
  if (status === "ok") return "Aktif";
  if (status === "insufficient_data") return "Pasif";
  return "Kismi";
}

function Badge({
  status,
  children,
}: {
  status: string;
  children: ReactNode;
}) {
  return <span className={`badge ${statusBadge(status)}`}>{children}</span>;
}
