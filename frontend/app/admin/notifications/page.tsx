"use client";

import { useEffect, useRef, useState } from "react";

interface NotificationSettings {
  emailAlerts: boolean;
  slackWebhook: string;
  jobFailures: boolean;
  killSwitchTriggers: boolean;
  strategyPromotions: boolean;
  dailyDigest: boolean;
}

const STORAGE_KEY = "borsa.notification-settings.v1";

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
  const [saved, setSaved] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const saveTimer = useRef<number | null>(null);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<NotificationSettings>;
        setSettings((prev) => ({ ...prev, ...parsed }));
      }
    } catch {
      // Ignore malformed storage and fall back to defaults.
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (saveTimer.current) {
        window.clearTimeout(saveTimer.current);
      }
    };
  }, []);

  function update<K extends keyof NotificationSettings>(key: K, value: NotificationSettings[K]) {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  function handleSave() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
      setSaved(true);
      if (saveTimer.current) {
        window.clearTimeout(saveTimer.current);
      }
      saveTimer.current = window.setTimeout(() => setSaved(false), 3000);
    } catch {
      setSaved(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Notification Settings</h1>
        <p className="text-slate-400 text-sm">Configure alerts and integrations. Saved in this browser.</p>
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-800 p-6 space-y-6">
        {/* Email Alerts */}
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium text-white">Email Alerts</div>
            <div className="text-xs text-slate-400">Receive email notifications for important events.</div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={settings.emailAlerts}
              onChange={(e) => update("emailAlerts", e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600" />
          </label>
        </div>

        {/* Slack Webhook */}
        <div className="space-y-2">
          <label className="text-sm font-medium text-white">Slack Webhook URL</label>
          <input
            type="text"
            value={settings.slackWebhook}
            onChange={(e) => update("slackWebhook", e.target.value)}
            placeholder="https://hooks.slack.com/services/..."
            className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-white text-sm placeholder-slate-500"
          />
          <p className="text-xs text-slate-400">Optional. Send alerts to a Slack channel.</p>
          <p className="text-xs text-slate-500">Stored locally in this browser.</p>
        </div>

        <div className="border-t border-slate-700 pt-6 space-y-4">
          <div className="text-sm font-medium text-white">Event Types</div>

          <ToggleRow
            label="Job Failures"
            desc="Alert when a pipeline job fails."
            checked={settings.jobFailures}
            onChange={(v) => update("jobFailures", v)}
          />
          <ToggleRow
            label="Kill Switch Triggers"
            desc="Alert when the kill switch is activated."
            checked={settings.killSwitchTriggers}
            onChange={(v) => update("killSwitchTriggers", v)}
          />
          <ToggleRow
            label="Strategy Promotions"
            desc="Alert when a strategy is promoted."
            checked={settings.strategyPromotions}
            onChange={(v) => update("strategyPromotions", v)}
          />
          <ToggleRow
            label="Daily Digest"
            desc="Send a daily summary of system activity."
            checked={settings.dailyDigest}
            onChange={(v) => update("dailyDigest", v)}
          />
        </div>

        <div className="flex items-center gap-4 pt-2">
          <button
            onClick={handleSave}
            disabled={!hydrated}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium disabled:opacity-60 disabled:cursor-not-allowed"
          >
            Save Settings
          </button>
          {saved && <span className="text-sm text-green-400">Settings saved locally.</span>}
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
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <div className="text-sm text-white">{label}</div>
        <div className="text-xs text-slate-400">{desc}</div>
      </div>
      <label className="relative inline-flex items-center cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only peer"
        />
        <div className="w-11 h-6 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600" />
      </label>
    </div>
  );
}
