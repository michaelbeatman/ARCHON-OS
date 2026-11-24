# -*- coding: utf-8 -*-
"""
backend/cancellation.py
=======================
Zentrale Cancel-Token-Propagation für Archon OS.

Ein Token ist pro Scope (z. B. ``boardroom:<task_id>``, ``dispatch:<task_id>``,
``run:<run_id>``) eindeutig registriert. ``cancel_scope()`` kann aus einem
Request-Handler, einem Hintergrund-Thread oder einer SSE-Schleife aufgerufen
werden und bricht alle verknüpften Kind-Tokens (Mission Control → Dispatch →
DAG → Boardroom) mit.

Das Modul ist absichtlich leichtgewichtig und ohne externe Abhängigkeiten,
damit es von allen Schichten importiert werden kann.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Dict, List, Optional

logger = logging.getLogger("archon_os.cancellation")


class CancelToken:
    """Ein abbrechbarer Scope mit Kind-Tokens und async-Wait."""

    def __init__(self, scope: str, parent: Optional["CancelToken"] = None) -> None:
        self.scope = str(scope)
        self._parent = parent
        self._children: List["CancelToken"] = []
        self._lock = threading.Lock()
        self._cancelled = False
        self._reason = ""
        self._event = asyncio.Event()
        # Registrierte Tasks: cancel() muss nicht nur ein Flag setzen, sondern
        # laufende LLM-Calls wirklich abbrechen (Audit 23.11.2026).
        self._tasks: set = set()
        try:
            self._loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        if parent is not None:
            parent._children.append(self)
            if parent.cancelled:
                self.cancel(parent.reason)

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def _set_event(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._event.set)
            except RuntimeError:
                pass
        else:
            try:
                self._event.set()
            except RuntimeError:
                pass

    def register_task(self, task: "asyncio.Task") -> None:
        """Task an diesen Scope binden, damit cancel() ihn wirklich abbricht."""
        with self._lock:
            self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def cancel(self, reason: str = "") -> None:
        """Bricht diesen Scope, alle Kinder und registrierten Tasks ab."""
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            self._reason = str(reason or "")
            children = list(self._children)
            tasks = list(self._tasks)
        for task in tasks:
            try:
                if task.done():
                    continue
                loop = self._loop
                if loop is not None and loop.is_running():
                    # task.cancel() ist nicht thread-safe. cancel_scope() wird
                    # auch aus sync Request-Handlern gerufen (Audit 23.11.).
                    loop.call_soon_threadsafe(task.cancel)
                else:
                    task.cancel()
            except Exception:
                pass
        for child in children:
            child.cancel(self._reason)
        self._set_event()

    async def wait(self, timeout: Optional[float] = None) -> bool:
        """Wartet auf Abbruch; liefert True, wenn der Token abgebrochen ist."""
        if self.cancelled:
            return True
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return self.cancelled
        return self.cancelled

    def check(self) -> None:
        """Wirft CancelledError, wenn der Scope abgebrochen wurde."""
        if self.cancelled:
            logger.info(
                "[CancelToken] check() abbrechen: scope=%s reason=%s",
                self.scope, self.reason,
            )
            raise asyncio.CancelledError(
                f"{self.scope} abgebrochen{': ' + self.reason if self.reason else ''}"
            )

    def child(self, scope: str) -> "CancelToken":
        """Erzeugt einen Kind-Token, der den Abbruch des Parents erbt."""
        return CancelToken(scope, parent=self)


_REGISTRY: Dict[str, CancelToken] = {}
_REGISTRY_LOCK = threading.Lock()
# E (Härtungsaudit): analog workflow_dag_runner._MAX_RUN_LOCKS — die Registry
# wuchs frueher pro Task/Session unbegrenzt und hielt gecancelte Tokens ewig.
_MAX_CANCEL_TOKENS = 512


def _evict_if_needed_locked() -> None:
    """Cap einhalten; zuerst gecancelte, dann die aeltesten Tokens entfernen.

    Muß mit gehaltenem ``_REGISTRY_LOCK`` aufgerufen werden.
    """
    overflow = len(_REGISTRY) - _MAX_CANCEL_TOKENS
    if overflow <= 0:
        return
    for key in [k for k, t in _REGISTRY.items() if t.cancelled][:overflow]:
        token = _REGISTRY.pop(key, None)
        if token is not None:
            parent = getattr(token, "_parent", None)
            if parent is not None:
                try:
                    parent._children.remove(token)
                except ValueError:
                    pass
    overflow = len(_REGISTRY) - _MAX_CANCEL_TOKENS
    if overflow > 0:
        for key in list(_REGISTRY)[:overflow]:
            _REGISTRY.pop(key, None)


def reset_scope(scope: str) -> bool:
    """E: Scope samt Kind-Tokens entfernen, damit ein neuer Lauf frische Tokens bekommt.

    ``cancel_scope()`` setzt das Flag dauerhaft; ein gecancelter ``task:<id>``-
    Token liess einen spaeter erneut gestarteten Worker sofort in
    ``CancelledError`` laufen, ohne Status-Update. Kinder (dispatch/run) werden
    mit entfernt, sonst bleibt der neue Root-Token mit gecancelten Kindern.
    """
    key = str(scope)
    with _REGISTRY_LOCK:
        root = _REGISTRY.get(key)
        if root is None:
            return False
        doomed = {key}
        frontier = [root]
        while frontier:
            parent = frontier.pop()
            for child in list(getattr(parent, "_children", ())):
                child_key = str(getattr(child, "scope", ""))
                if child_key and _REGISTRY.get(child_key) is child and child_key not in doomed:
                    doomed.add(child_key)
                    frontier.append(child)
        for k in doomed:
            token = _REGISTRY.pop(k, None)
            if token is not None:
                parent = getattr(token, "_parent", None)
                if parent is not None:
                    try:
                        parent._children.remove(token)
                    except ValueError:
                        pass
        return True


def get_token(scope: str, *, create: bool = True, reset: bool = False) -> Optional[CancelToken]:
    """Liefert den Token für einen Scope (optional neu anlegen).

    ``reset=True`` entfernt einen vorhandenen Token (inkl. Kinder) zuerst —
    für erneute Läufe desselben Scopes nach einem Cancel.
    """
    key = str(scope)
    if reset:
        reset_scope(key)
    with _REGISTRY_LOCK:
        token = _REGISTRY.get(key)
        if token is None and create:
            token = CancelToken(key)
            _REGISTRY[key] = token
        _evict_if_needed_locked()
        return token


def get_child_token(parent_scope: str, child_scope: str) -> CancelToken:
    """Kind-Token mit registriertem Parent (Propagation bei cancel_scope())."""
    parent = get_token(parent_scope)
    assert parent is not None
    key = str(child_scope)
    with _REGISTRY_LOCK:
        token = _REGISTRY.get(key)
        if token is None:
            token = parent.child(key)
            _REGISTRY[key] = token
        else:
            # FRUEHER: ein bereits registrierter Token (z. B. vorher als
            # Root-Token 'dispatch:id' erzeugt) blieb an seinem alten Parent —
            # cancel_scope('task:id') erreichte Dispatch/DAG nicht. Jetzt
            # neu verkabeln, aber nie einen bereits abgebrochenen Token
            # wiederbeleben.
            old_parent = getattr(token, "_parent", None)
            if old_parent is not parent:
                if old_parent is not None:
                    try:
                        old_parent._children.remove(token)
                    except ValueError:
                        pass
                token._parent = parent
                parent._children.append(token)
                if parent.cancelled:
                    token.cancel(parent.reason)
        _evict_if_needed_locked()
        return token


def cancel_scope(scope: str, reason: str = "") -> bool:
    """Bricht einen registrierten Scope ab. False, wenn er nicht existiert."""
    with _REGISTRY_LOCK:
        token = _REGISTRY.get(str(scope))
    if token is None:
        return False
    token.cancel(reason)
    return True


def clear_scope(scope: str) -> None:
    """Entfernt einen Scope aus der Registry (z. B. nach Abschluss).

    Der Parent darf dabei keine dauerhafte Referenz auf das Kind behalten —
    sonst waechst ``parent._children`` bei jeder Debatte unbegrenzt und der
    Killswitch iteriert über verwaiste Tokens (Audit 23.11.2026).
    """
    with _REGISTRY_LOCK:
        token = _REGISTRY.pop(str(scope), None)
    if token is not None:
        parent = getattr(token, "_parent", None)
        if parent is not None:
            try:
                parent._children.remove(token)
            except ValueError:
                pass
