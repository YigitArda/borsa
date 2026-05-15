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
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Notification Settings</h1>
        <p className="text-slate-400 text-sm">
          Configure alerts and integrations. Settings are stored on the server and shared across devices.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-700/40 bg-red-900/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-6">
        {loading ? (
          <div className="text-sm text-slate-400">Loading notification settings...</div>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-white">Email Alerts</div>
                <div className="text-xs text-slate-400">Receive email notifications for important events.</div>
              </div>
              <Toggle
                checked={settings.emailAlerts}
                onChange={(value) => update("emailAlerts", value)}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-white">Slack Webhook URL</label>
              <input
                type="text"
                value={settings.slackWebhook}
                onChange={(e) => update("slackWebhook", e.target.value)}
                placeholder="https://hooks.slack.com/services/..."
                className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm placeholder-slate-500"
              />
              <p className="text-xs text-slate-400">
                Optional. Slack delivery falls back to this value when a per-event webhook is not provided.
              </p>
            </div>

            <div className="border-t border-slate-700 pt-6 space-y-4">
              <div className="text-sm font-medium text-white">Event Types</div>

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

            <div className="flex items-center gap-4 pt-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {saving ? "Saving..." : "Save Settings"}
              </button>
              {saved && <span className="text-sm text-green-400">Settings saved on the server.</span>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="relative inline-flex items-center cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only peer"
      />
      <div className="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600" />
    </label>
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
    <div className="flex items-center justify-between">
      <div>
        <div className="text-sm text-white">{label}</div>
        <div className="text-xs text-slate-400">{desc}</div>
      </div>
      <Toggle checked={checked} onChange={onChange} />
    </div>
  );
}
