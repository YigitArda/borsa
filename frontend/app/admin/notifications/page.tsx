"use client";

import { useEffect, useState } from "react";
import { notifications, type NotificationSettings } from "@/lib/api";

const DEFAULT_SETTINGS: NotificationSettings = {
  emailAlerts: true,
  slackWebhook: "",
  jobFailures: true,
  killSwitchTriggers: true,
  strategyPromotions: false,
  dailyDigest: false,
};

export default function NotificationsPage() {
  const [settings, setSettings] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const data = await notifications.getSettings();
        if (!active) return;
        setSettings({ ...DEFAULT_SETTINGS, ...data });
        setError(null);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Notification settings could not be loaded.");
      } finally {
        if (active) setLoading(false);
      }
    }

    load();
    return () => {
      active = false;
    };
  }, []);

  function update<K extends keyof NotificationSettings>(key: K, value: NotificationSettings[K]) {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const savedSettings = await notifications.saveSettings(settings);
      setSettings({ ...DEFAULT_SETTINGS, ...savedSettings });
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Notification settings could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ maxWidth: "840px", margin: "0 auto" }}>
      <h1>Notification Settings</h1>
      <p style={{ marginBottom: "10px", color: "#666", fontSize: "11px" }}>
        Configure alert delivery for jobs, kill switch and promotions.
      </p>

      {error && <div className="alert alert-danger">{error}</div>}

      <div className="box">
        <div className="box-head">Delivery Settings</div>
        <div className="box-body" style={{ display: "grid", gap: "12px" }}>
          {loading ? (
            <div style={{ color: "#666", fontSize: "11px" }}>Loading notification settings...</div>
          ) : (
            <>
              <ToggleRow
                label="Email Alerts"
                desc="Receive email notifications for important events."
                checked={settings.emailAlerts}
                onChange={(value) => update("emailAlerts", value)}
              />

              <div>
                <div className="section-label">Slack Webhook URL</div>
                <input
                  type="text"
                  value={settings.slackWebhook}
                  onChange={(e) => update("slackWebhook", e.target.value)}
                  placeholder="https://hooks.slack.com/services/..."
                  style={{ width: "100%" }}
                />
                <div style={{ fontSize: "10px", color: "#666", marginTop: "4px" }}>
                  Optional. Slack delivery falls back to this value when a per-event webhook is not provided.
                </div>
              </div>

              <div className="box" style={{ marginBottom: 0 }}>
                <div className="box-head">Event Types</div>
                <div className="box-body" style={{ display: "grid", gap: "10px" }}>
                  <ToggleRow
                    label="Job Failures"
                    desc="Alert when a pipeline job fails."
                    checked={settings.jobFailures}
                    onChange={(value) => update("jobFailures", value)}
                  />
                  <ToggleRow
                    label="Kill Switch Triggers"
                    desc="Alert when the kill switch is activated."
                    checked={settings.killSwitchTriggers}
                    onChange={(value) => update("killSwitchTriggers", value)}
                  />
                  <ToggleRow
                    label="Strategy Promotions"
                    desc="Alert when a strategy is promoted."
                    checked={settings.strategyPromotions}
                    onChange={(value) => update("strategyPromotions", value)}
                  />
                  <ToggleRow
                    label="Daily Digest"
                    desc="Send a daily summary of system activity."
                    checked={settings.dailyDigest}
                    onChange={(value) => update("dailyDigest", value)}
                  />
                </div>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <button onClick={handleSave} disabled={saving}>
                  {saving ? "Saving..." : "Save Settings"}
                </button>
                {saved && <span className="text-green">Settings saved on the server.</span>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  desc,
  checked,
  onChange,
}: {
  label: string;
  desc: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px" }}>
      <div>
        <div style={{ fontSize: "11px", fontWeight: "bold" }}>{label}</div>
        <div style={{ fontSize: "10px", color: "#666" }}>{desc}</div>
      </div>
      <label style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span style={{ fontSize: "10px" }}>{checked ? "On" : "Off"}</span>
      </label>
    </div>
  );
}
