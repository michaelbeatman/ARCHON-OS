"use client";

import React, { useEffect, useRef, useState } from 'react';
import { archonFetch } from '@/lib/archon-api';

/**
 * EU AI Act Art. 50 — nicht wegklickbarer Client-Freigabe-Dialog.
 *
 * Die Challenge stammt ausschliesslich aus
 * `backend.client_approval_portal.verify_share_access(..., issue_disclosure_challenge=True,
 * disclosure_session=...)`. Dieses Modul erfindet weder einen Endpoint noch Werte:
 * der Host uebergibt das vom Server signierte Ergebnis (token, ai_disclosure_token,
 * ai_disclosure_nonce, ai_disclosure_session) als Prop. Ohne Host-Einbau bleibt der
 * Flow bewusst `not_configured` — siehe audit_reports/fix_d4_frontend.md (DELEGATED).
 */
export interface ClientDisclosureChallenge {
  token: string;
  ai_disclosure_token: string;
  ai_disclosure_nonce: string;
  ai_disclosure_session: string;
  title?: string;
  offer_id?: string;
  password_protected?: boolean;
}

interface ClientApprovalPortalProps {
  challenge: ClientDisclosureChallenge;
  onDecided?: (result: Record<string, unknown>) => void;
}

type Decision = 'accepted' | 'changes_requested' | 'declined';

export function ClientApprovalPortal({ challenge, onDecided }: ClientApprovalPortalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const [disclosureConfirmed, setDisclosureConfirmed] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [decision, setDecision] = useState<Decision>('accepted');
  const [comment, setComment] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // Nicht wegklickbar: kein Schliess-Button, kein Backdrop-Handler. Escape wird
  // abgefangen statt zu schliessen; der Fokus bleibt im Dialog (Tab-Falle).
  useEffect(() => {
    const dialog = dialogRef.current;
    confirmRef.current?.focus();
    const focusableItems = () => Array.from(
      dialog?.querySelectorAll<HTMLElement>(
        'input:not([disabled]), button:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ) ?? []
    );
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusableItems();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!dialog?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!disclosureConfirmed) {
      setError('Der KI-Transparenzhinweis muss explizit bestaetigt werden.');
      return;
    }
    if (decision === 'accepted' && !termsAccepted) {
      setError('Die Annahme setzt die explizite AGB-/Vertragsbestaetigung voraus.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      // Browser -> Same-Origin-Proxy -> POST /api/v2/portal/decisions.
      const res = await archonFetch<Record<string, unknown>>('api/v2/portal/decisions', {
        method: 'POST',
        body: JSON.stringify({
          token: challenge.token,
          decision,
          comment,
          password,
          terms_accepted: termsAccepted,
          // Art. 50: explizite Bestaetigung + signierter Token + die vom
          // Server bei verify_share_access() gedrehte Nonce/Session.
          ai_disclosure_shown: true,
          ai_disclosure_token: challenge.ai_disclosure_token,
          ai_disclosure_nonce: challenge.ai_disclosure_nonce,
          ai_disclosure_session: challenge.ai_disclosure_session,
        }),
      });
      onDecided?.(res);
    } catch (err: any) {
      setError(err?.message || 'Die Entscheidung konnte nicht uebermittelt werden.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="client-portal-art50-title"
        tabIndex={-1}
        className="w-full max-w-xl rounded-2xl border border-slate-300 bg-white p-6 text-slate-900 shadow-2xl space-y-4"
      >
        <h2 id="client-portal-art50-title" className="text-base font-bold">
          KI-Transparenzhinweis (EU AI Act Art. 50)
        </h2>
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
          <p>
            Die Unterlagen zu diesem Angebot{challenge.title ? ` („${challenge.title}“)` : ''}{' '}
            wurden unter Einsatz eines KI-Systems vorbereitet. Die KI hat keine
            Entscheidungsbefugnis; die nachstehende Entscheidung wird von Ihnen als
            verantwortlicher Person getroffen und ist verbindlich. Bitte pruefen Sie
            die Unterlagen inhaltlich, bevor Sie entscheiden.
          </p>
        </div>
        <p className="text-[11px] text-slate-500">
          Aus technischen und rechtlichen Gruenden kann dieser Hinweis nicht
          uebersprungen oder weggeklickt werden.
        </p>

        {error && (
          <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 p-2 text-xs text-rose-700">
            {error}
          </div>
        )}

        <form onSubmit={submit} className="space-y-3 text-xs">
          <label className="flex items-start gap-2 font-semibold cursor-pointer">
            <input
              ref={confirmRef}
              type="checkbox"
              checked={disclosureConfirmed}
              onChange={(e) => setDisclosureConfirmed(e.target.checked)}
              className="mt-0.5"
            />
            <span>Ich habe den KI-Transparenzhinweis gelesen und bestaetige ihn ausdruecklich.</span>
          </label>

          {challenge.password_protected && (
            <label className="block space-y-1">
              <span className="font-semibold">Passwort des Freigabelinks</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 outline-none focus:border-emerald-500"
              />
            </label>
          )}

          <label className="block space-y-1">
            <span className="font-semibold">Entscheidung</span>
            <select
              value={decision}
              onChange={(e) => setDecision(e.target.value as Decision)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 outline-none focus:border-emerald-500"
            >
              <option value="accepted">Angebot annehmen</option>
              <option value="changes_requested">Aenderungen wuenschen</option>
              <option value="declined">Ablehnen</option>
            </select>
          </label>

          {decision === 'accepted' && (
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={termsAccepted}
                onChange={(e) => setTermsAccepted(e.target.checked)}
                className="mt-0.5"
              />
              <span>Ich bestaetige die AGB-/Vertragsbedingungen ausdruecklich.</span>
            </label>
          )}

          <label className="block space-y-1">
            <span className="font-semibold">Kommentar (optional)</span>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 outline-none focus:border-emerald-500"
            />
          </label>

          <button
            type="submit"
            disabled={busy || !disclosureConfirmed}
            className="w-full rounded-lg bg-emerald-600 px-4 py-2.5 font-bold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? 'Wird uebermittelt...' : 'Entscheidung verbindlich senden'}
          </button>
        </form>
      </div>
    </div>
  );
}
