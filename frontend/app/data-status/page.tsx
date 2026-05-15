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

function statusClasses(status: string) {
  if (status === "Aktif") return "bg-green-500/10 text-green-300 border-green-700/40";
  if (status === "Kismi") return "bg-yellow-500/10 text-yellow-300 border-yellow-700/40";
  if (status === "Pasif") return "bg-red-500/10 text-red-300 border-red-700/40";
  return "bg-slate-500/10 text-slate-300 border-slate-600";
}

export default async function DataStatusPage() {
  const { data, error } = await loadApi<DataStatusSummary>("/data-quality/summary");
  const summary = data;
  const generatedAt = summary ? new Date(summary.generated_at).toLocaleString("tr-TR") : null;

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Veri Durumu Raporu</h1>
        <p className="text-slate-400 text-sm">
          Sistemdeki veri kaynakları, kapsam ve çalışma durumu tek bir backend özetinden okunur.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-700/40 bg-red-900/10 p-4 text-sm text-red-300">
          Veri özeti yüklenemedi: {error}
        </div>
      )}

      {summary ? (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <StatCard label="Aktif Hisse" value={summary.stock_count} />
            <StatCard label="Fiyat Kayıtları" value={summary.price_coverage.total_rows} />
            <StatCard label="Feature Kayıtları" value={summary.feature_coverage.total_rows} />
            <StatCard label="Label Kayıtları" value={summary.label_coverage.total_rows} />
            <StatCard label="Veri Kaynağı" value={summary.data_sources.length} />
          </div>

          <div className="rounded-lg border border-slate-700 bg-slate-800 p-4 text-sm text-slate-300">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs uppercase tracking-wide text-slate-500">Son güncelleme</div>
                <div className="text-white font-medium">{generatedAt ?? "Bilinmiyor"}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-slate-500">Fiyat aralığı</div>
                <div className="text-white font-medium">
                  {summary.price_coverage.range_start ?? "N/A"} - {summary.price_coverage.range_end ?? "N/A"}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-slate-500">Feature aileleri</div>
                <div className="text-white font-medium">{summary.feature_coverage.categories.length}</div>
              </div>
            </div>
          </div>

          <Section title="Veri Kaynakları ve Durumları">
            <DataTable
              headers={["Veri Tipi", "Kaynak", "Periyot", "Tarih Aralığı", "Toplam Kayıt", "Kapsam", "Durum"]}
              rows={summary.data_sources.map((row) => [
                <strong key={`${row.name}-name`}>{row.name}</strong>,
                row.source,
                row.period,
                <span key={`${row.name}-range`} className="font-mono text-xs">{row.range}</span>,
                row.totalRecords,
                row.coverage,
                <Badge key={`${row.name}-status`} status={row.status}>{row.status.toUpperCase()}</Badge>,
              ])}
            />
          </Section>

          <Section title="Hisse Başına Fiyat Verisi">
            <DataTable
              headers={["#", "Ticker", "Hafta", "Yıl", "Başlangıç", "Bitiş"]}
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
              headers={["Kategori", "Sayı", "Örnekler"]}
              rows={summary.feature_coverage.categories.map((row) => [
                <strong key={`${row.category}-category`}>{row.category}</strong>,
                row.count,
                row.examples,
              ])}
            />
          </Section>

          <Section title="Sistem Durumu">
            <DataTable
              headers={["Bileşen", "Durum", "Detay"]}
              rows={summary.system_status.map((row) => [
                <strong key={`${row.name}-name`}>{row.name}</strong>,
                <Badge key={`${row.name}-status`} status={row.status}>{row.status.toUpperCase()}</Badge>,
                row.detail,
              ])}
            />
          </Section>
        </>
      ) : (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 text-sm text-slate-400">
          Veri özeti şu anda alınamadı. Backend tekrar çevrimiçi olduğunda bu sayfa otomatik olarak güncellenecek.
        </div>
      )}

      <div className="text-center text-[10px] text-slate-500 border border-slate-700 bg-slate-800/60 rounded px-3 py-2">
        Bu sistem yalnızca araştırma amaçlıdır, yatırım tavsiyesi değildir.
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-700 bg-slate-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700 bg-slate-900/70 text-sm font-semibold text-white">
        {title}
      </div>
      <div className="overflow-x-auto">{children}</div>
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
    <table className="w-full text-sm">
      <thead className="bg-slate-900 text-slate-400">
        <tr>
          {headers.map((header) => (
            <th key={header} className="px-4 py-3 text-left whitespace-nowrap">
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={headers.length} className="px-4 py-6 text-slate-400">
              Veri bulunamadı.
            </td>
          </tr>
        ) : (
          rows.map((cells, rowIndex) => (
            <tr key={rowIndex} className="border-t border-slate-700 hover:bg-slate-700/30">
              {cells.map((cell, cellIndex) => (
                <td key={cellIndex} className="px-4 py-3 text-slate-300 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-bold text-white">
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
    </div>
  );
}

function Badge({
  status,
  children,
}: {
  status: string;
  children: ReactNode;
}) {
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold border ${statusClasses(status)}`}>
      {children}
    </span>
  );
}
