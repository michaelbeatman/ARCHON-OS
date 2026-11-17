"use client";

import React, { useEffect } from "react";

export default function CrmError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[ARCHON CRM ErrorBoundary]", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6 font-sans">
      <div className="max-w-md w-full rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl space-y-4 text-center">
        <h2 className="text-lg font-bold text-rose-400">
          CRM-Ansicht konnte nicht gerendert werden
        </h2>
        <p className="text-xs text-slate-400 font-mono break-words">
          {error?.message || "Unbekannter Laufzeitfehler"}
        </p>
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            type="button"
            onClick={() => reset()}
            className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold cursor-pointer transition"
          >
            Erneut versuchen
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg border border-slate-700 hover:bg-slate-800 text-slate-300 text-xs font-bold cursor-pointer transition"
          >
            Seite neu laden
          </button>
        </div>
      </div>
    </div>
  );
}
