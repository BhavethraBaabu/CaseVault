"use client";

import { useEffect, useState } from "react";
import { fetchHealth, type HealthResponse } from "@/lib/api";

type Status = "loading" | "ok" | "error";

export default function HealthStatus() {
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<HealthResponse | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((d) => {
        setData(d);
        setStatus("ok");
      })
      .catch(() => {
        setStatus("error");
      });
  }, []);

  const dot: Record<Status, string> = {
    loading: "bg-slate-300 animate-pulse",
    ok: "bg-emerald-500",
    error: "bg-red-400",
  };

  const label: Record<Status, string> = {
    loading: "Connecting...",
    ok: "Backend connected",
    error: "Backend unavailable",
  };

  return (
    <div className="flex items-center gap-2 text-sm text-slate-600">
      <span className={`inline-block w-2 h-2 rounded-full ${dot[status]}`} />
      <span>{label[status]}</span>
      {data && (
        <span className="text-slate-400 text-xs">
          (v{data.version} · db: {data.database})
        </span>
      )}
    </div>
  );
}
