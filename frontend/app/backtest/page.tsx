"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export default function BacktestLandingPage() {
  const router = useRouter();
  const [runId, setRunId] = useState("");
  const [error, setError] = useState<string | null>(null);

  function openRun() {
    const id = Number(runId.trim());
    if (!Number.isInteger(id) || id <= 0) {
      setError("Gecerli bir backtest ID gir.");
      return;
    }
    setError(null);
    router.push(`/backtest/${id}`);
  }

  return (
    <div style={{ maxWidth: "960px", margin: "0 auto" }}>
      <h1>Backtest Merkezi</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Calistirilmis backtest sonuclarini ac veya yeni bir research akisi icin Strategy Lab'e gec.
      </p>

      <div className="alert alert-info">
        <b>Not:</b> Bu sayfa bir listedeki run'lara baglanmiyor. Dogrudan ID ile aciliyor.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "12px" }}>
        <div className="box">
          <div className="box-head">Backtest ID ile ac</div>
          <div className="box-body" style={{ display: "grid", gap: "8px" }}>
            <div style={{ fontSize: "11px", color: "#666" }}>
              `backtest/[id]` detay sayfasina gitmek icin ID yaz.
            </div>
            <input
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && openRun()}
              inputMode="numeric"
              placeholder="Orn. 12"
            />
            <div>
              <button onClick={openRun}>Ac</button>
            </div>
            {error && <div className="text-red">{error}</div>}
          </div>
        </div>

        <div className="box">
          <div className="box-head">Yeni backtest calistir</div>
          <div className="box-body" style={{ display: "grid", gap: "8px" }}>
            <div style={{ fontSize: "11px", color: "#666" }}>
              Parametre secimi ve direct backtest icin Strategy Lab'i kullan.
            </div>
            <Link href="/strategy-lab" className="btn" prefetch={false}>
              Strategy Lab'e git
            </Link>
          </div>
        </div>
      </div>

      <div className="box" style={{ marginTop: "12px" }}>
        <div className="box-head">Bilgi</div>
        <div className="box-body">
          <ul style={{ paddingLeft: "18px", lineHeight: 1.6 }}>
            <li>Bu sayfa sadece rota 404'ünü kapatir.</li>
            <li>Backtest verisi backend'den <code>GET /backtest/&lt;id&gt;</code> ile gelir.</li>
            <li>Henuz listeleme endpoint'i yok.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
