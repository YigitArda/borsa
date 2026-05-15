"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function BacktestLandingPage() {
  const router = useRouter();
  const [runId, setRunId] = useState("");
  const [error, setError] = useState<string | null>(null);

  function openRun() {
    const id = Number(runId.trim());
    if (!Number.isInteger(id) || id <= 0) {
      setError("Geçerli bir backtest ID gir.");
      return;
    }
    setError(null);
    router.push(`/backtest/${id}`);
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Backtest Merkezi</h1>
        <p className="text-slate-400 text-sm mt-1">
          Çalıştırılmış backtest sonuçlarını aç veya yeni bir araştırma için Strategy Lab’e geç.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4 space-y-3">
          <h2 className="text-lg font-semibold text-white">Backtest ID ile aç</h2>
          <p className="text-sm text-slate-400">
            `backtest/[id]` detay sayfası mevcut. Buraya ID yazıp doğrudan açabilirsin.
          </p>
          <div className="flex gap-2">
            <input
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && openRun()}
              inputMode="numeric"
              placeholder="Örn. 12"
              className="flex-1 rounded border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white outline-none"
            />
            <button
              onClick={openRun}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
            >
              Aç
            </button>
          </div>
          {error && <div className="text-sm text-red-400">{error}</div>}
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4 space-y-3">
          <h2 className="text-lg font-semibold text-white">Yeni backtest çalıştır</h2>
          <p className="text-sm text-slate-400">
            Parametre seçimi, direct backtest ve research loop için Strategy Lab’i kullan.
          </p>
          <a
            href="/strategy-lab"
            className="inline-flex rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
          >
            Strategy Lab’e git
          </a>
        </div>
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h2 className="text-lg font-semibold text-white mb-2">Not</h2>
        <ul className="text-sm text-slate-400 space-y-1 list-disc pl-5">
          <li>Bu sayfa sadece rota 404’ünü kapatır.</li>
          <li>Backtest verisi backend’den <code>GET /backtest/&lt;id&gt;</code> ile gelir.</li>
          <li>Henüz listeleme endpoint’i yok; bu yüzden direkt ID ile açılıyor.</li>
        </ul>
      </div>
    </div>
  );
}
