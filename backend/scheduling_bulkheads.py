# -*- coding: utf-8 -*-
"""M111: Bulkhead-Scheduling mit getrennten Klassen und harter Backpressure.

Drei Scheduling-Klassen (``chat``, ``background_dag``, ``eval``) besitzen je
eine eigene Kapazitaet und eine eigene, ENDLICHE Warteschlange. Ist beides
belegt, wird der Dispatch abgelehnt (Reject) statt ueberbucht. Es gibt keine
Datenbank-Tabelle und keine globale Semaphore, die eine Klasse auf Kosten der
anderen blockieren koennte.

Die Sperre ist ein ``threading.Lock``: Akquisition und Snapshot sind kurz und
blockieren nicht im Event-Loop; asynchrone Aufrufer warten ausschliesslich auf
einem ``asyncio.Future`` (kein ``threading.Event.wait()`` im Loop).
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import threading
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Deque, Dict, Literal, Mapping, Optional

SchedulingClass = Literal["chat", "background_dag", "eval"]

SCHEDULING_CLASSES: tuple[SchedulingClass, ...] = ("chat", "background_dag", "eval")


@dataclass(frozen=True)
class BulkheadConfig:
    """Harte Kapazitaetsgrenzen einer Scheduling-Klasse."""

    capacity: int = 1
    max_queue: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "capacity", max(1, int(self.capacity)))
        object.__setattr__(self, "max_queue", max(0, int(self.max_queue)))


# Kapazitaet = gleichzeitig laufende Slots, max_queue = zulaessige wartende
# Dispatches. Chat bleibt interaktiv grosszuegig, Eval ist bewusst knapp.
DEFAULT_BULKHEAD_CONFIGS: Dict[SchedulingClass, BulkheadConfig] = {
    "chat": BulkheadConfig(capacity=8, max_queue=16),
    "background_dag": BulkheadConfig(capacity=4, max_queue=32),
    "eval": BulkheadConfig(capacity=2, max_queue=8),
}

_CLASS_ALIASES: Dict[str, SchedulingClass] = {
    "dag": "background_dag",
    "background": "background_dag",
    "background-dag": "background_dag",
    "background_dags": "background_dag",
    "interactive": "chat",
    "ui": "chat",
    "evaluation": "eval",
    "evals": "eval",
}


def normalize_scheduling_class(value: Any, default: SchedulingClass = "chat") -> SchedulingClass:
    """Normalisiert Aliase; unbekannte Werte fallen auf ``default`` zurueck.

    Kein stilles Umleiten auf eine grosse Klasse: ein unbekannter Wert wird
    ausdruecklich auf den ueblichen interaktiven Pfad abgebildet.
    """
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("chat", "background_dag", "eval"):
        return key  # type: ignore[return-value]
    return _CLASS_ALIASES.get(key, default)


def load_bulkhead_configs() -> Dict[SchedulingClass, BulkheadConfig]:
    """Konfiguration aus der SSOT plus optionalen Env-Overrides.

    Env-Overrides erlauben Betriebsanpassungen ohne neue Tabelle und ohne
    Aenderung an ``settings.json`` (gehoert nicht zu M111).
    """
    configs: Dict[SchedulingClass, BulkheadConfig] = {}
    for cls in SCHEDULING_CLASSES:
        base = DEFAULT_BULKHEAD_CONFIGS[cls]
        prefix = f"ARCHON_BULKHEAD_{cls.upper()}"
        try:
            capacity = int(os.getenv(f"{prefix}_CAPACITY", str(base.capacity)))
        except (TypeError, ValueError):
            capacity = base.capacity
        try:
            max_queue = int(os.getenv(f"{prefix}_MAX_QUEUE", str(base.max_queue)))
        except (TypeError, ValueError):
            max_queue = base.max_queue
        configs[cls] = BulkheadConfig(capacity=capacity, max_queue=max_queue)
    return configs


_SCHEDULING_CLASS_CTX: contextvars.ContextVar[SchedulingClass] = contextvars.ContextVar(
    "archon_scheduling_class", default="chat"
)


def set_scheduling_class(value: Any) -> SchedulingClass:
    """Setzt die task-lokale Scheduling-Klasse fuer nachfolgende Dispatches."""
    cls = normalize_scheduling_class(value)
    _SCHEDULING_CLASS_CTX.set(cls)
    return cls


def current_scheduling_class() -> SchedulingClass:
    """Liefert die task-lokale Scheduling-Klasse (Default: ``chat``)."""
    return normalize_scheduling_class(_SCHEDULING_CLASS_CTX.get())


@dataclass
class BulkheadLease:
    """Ergebnis einer Kapazitaetsanfrage inklusive Backpressure-Signal.

    Ein abgelehnter Lease traegt ``granted=False``, einen stabilen
    ``error_code`` und ``retry_after_seconds``. Damit ist Ueberlast sichtbar,
    statt still einen Slot zu ueberbuchen.
    """

    scheduling_class: SchedulingClass
    owner_id: str = ""
    granted: bool = False
    queued: bool = False
    error_code: str = ""
    detail: str = ""
    backpressure: bool = False
    retry_after_seconds: float = 0.0
    _bulkhead: Optional["SchedulingBulkhead"] = field(default=None, repr=False, compare=False)
    _released: bool = field(default=False, repr=False, compare=False)

    def release(self) -> None:
        """Gibt einen gewaehrten Slot genau einmal frei."""
        if self.granted and not self._released and self._bulkhead is not None:
            self._bulkhead.release(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scheduling_class": self.scheduling_class,
            "owner_id": self.owner_id,
            "granted": self.granted,
            "queued": self.queued,
            "error_code": self.error_code,
            "detail": self.detail,
            "backpressure": self.backpressure,
            "retry_after_seconds": self.retry_after_seconds,
        }


class BulkheadRejected(RuntimeError):
    """Asynchrone Variante der Ablehnung (mit dem vollständigen Lease)."""

    def __init__(self, lease: BulkheadLease) -> None:
        super().__init__(f"{lease.error_code}: {lease.detail}")
        self.lease = lease


@dataclass
class _Waiter:
    future: asyncio.Future[bool]
    loop: asyncio.AbstractEventLoop
    scheduling_class: SchedulingClass


@dataclass
class _ClassState:
    active: int = 0
    waiters: Deque[_Waiter] = field(default_factory=deque)
    admitted: int = 0
    rejected: int = 0
    timed_out: int = 0


def _fulfil_waiter(future: asyncio.Future[bool]) -> None:
    """Spawnbar ueber ``call_soon_threadsafe``: nie eine geschlossene Future aendern."""
    if not future.done():
        future.set_result(True)


class SchedulingBulkhead:
    """Prozesslokale, thread-sichere Bulkheads fuer die drei Klassen."""

    def __init__(
        self,
        configs: Optional[Mapping[SchedulingClass, BulkheadConfig]] = None,
        *,
        retry_after_seconds: float = 0.5,
    ) -> None:
        self._configs: Dict[SchedulingClass, BulkheadConfig] = dict(
            configs if configs is not None else load_bulkhead_configs()
        )
        self._state: Dict[SchedulingClass, _ClassState] = {
            cls: _ClassState() for cls in SCHEDULING_CLASSES
        }
        self._lock = threading.Lock()
        self._retry_after = max(0.0, float(retry_after_seconds))

    def config(self, scheduling_class: Any) -> BulkheadConfig:
        cls = normalize_scheduling_class(scheduling_class)
        return self._configs.get(cls, DEFAULT_BULKHEAD_CONFIGS[cls])

    def try_acquire(self, scheduling_class: Any, owner_id: str = "") -> BulkheadLease:
        """Nicht blockierende Akquisition; bei Ueberlast sofort Reject."""
        cls = normalize_scheduling_class(scheduling_class)
        with self._lock:
            st = self._state[cls]
            cfg = self._configs.get(cls, DEFAULT_BULKHEAD_CONFIGS[cls])
            if st.active < cfg.capacity and not st.waiters:
                st.active += 1
                st.admitted += 1
                return BulkheadLease(
                    scheduling_class=cls, owner_id=str(owner_id), granted=True,
                    _bulkhead=self,
                )
            st.rejected += 1
            full = st.active >= cfg.capacity
            return BulkheadLease(
                scheduling_class=cls,
                owner_id=str(owner_id),
                error_code="BULKHEAD_CAPACITY_EXHAUSTED" if full else "BULKHEAD_QUEUE_CONTENDED",
                detail=(
                    f"{cls}: {st.active}/{cfg.capacity} Slots belegt"
                    if full else f"{cls}: wartende Anfragen haben Vorrang"
                ),
                backpressure=True,
                retry_after_seconds=self._retry_after,
            )

    async def acquire(
        self,
        scheduling_class: Any,
        owner_id: str = "",
        *,
        wait_seconds: float = 0.0,
    ) -> BulkheadLease:
        """Akquisition mit optionaler, STRENG begrenzter Queue.

        ``wait_seconds <= 0`` entspricht ``try_acquire``. Andernfalls darf die
        Anfrage maximal ``max_queue`` Plätze einnehmen; danach folgt Reject.
        """
        cls = normalize_scheduling_class(scheduling_class)
        loop = asyncio.get_running_loop()
        waiter: Optional[_Waiter] = None
        with self._lock:
            st = self._state[cls]
            cfg = self._configs.get(cls, DEFAULT_BULKHEAD_CONFIGS[cls])
            if st.active < cfg.capacity and not st.waiters:
                st.active += 1
                st.admitted += 1
                return BulkheadLease(
                    scheduling_class=cls, owner_id=str(owner_id), granted=True,
                    _bulkhead=self,
                )
            if wait_seconds > 0 and len(st.waiters) < cfg.max_queue:
                waiter = _Waiter(loop.create_future(), loop, cls)
                st.waiters.append(waiter)
            else:
                st.rejected += 1
                queue_full = len(st.waiters) >= cfg.max_queue
                return BulkheadLease(
                    scheduling_class=cls,
                    owner_id=str(owner_id),
                    error_code="BULKHEAD_QUEUE_FULL" if queue_full else "BULKHEAD_CAPACITY_EXHAUSTED",
                    detail=f"{cls}: Kapazitaet={cfg.capacity}, Queue={len(st.waiters)}/{cfg.max_queue}",
                    backpressure=True,
                    retry_after_seconds=self._retry_after,
                )

        assert waiter is not None  # noqa: S101 - durch obige Verzweigung garantiert
        try:
            await asyncio.wait_for(waiter.future, timeout=float(wait_seconds))
        except TimeoutError:
            self._abandon_waiter(waiter, timed_out=True)
            with self._lock:
                self._state[cls].rejected += 1
            return BulkheadLease(
                scheduling_class=cls,
                owner_id=str(owner_id),
                error_code="BULKHEAD_QUEUE_TIMEOUT",
                detail=f"{cls}: kein Slot binnen {wait_seconds}s frei geworden",
                backpressure=True,
                retry_after_seconds=self._retry_after,
            )
        except BaseException:
            # CancelledError (und alle weiteren BaseExceptions) duerfen keinen
            # reservierten Slot und keinen Geist-Waiter hinterlassen.
            self._abandon_waiter(waiter, timed_out=False)
            raise
        with self._lock:
            self._state[cls].admitted += 1
        return BulkheadLease(
            scheduling_class=cls, owner_id=str(owner_id), granted=True, _bulkhead=self,
        )

    @asynccontextmanager
    async def slot(
        self,
        scheduling_class: Any,
        owner_id: str = "",
        *,
        wait_seconds: float = 0.0,
    ) -> AsyncIterator[BulkheadLease]:
        """Bidirektionaler Kontextmanager; lehnt Ueberlast mit Exception ab."""
        lease = await self.acquire(scheduling_class, owner_id, wait_seconds=wait_seconds)
        if not lease.granted:
            raise BulkheadRejected(lease)
        try:
            yield lease
        finally:
            lease.release()

    def _abandon_waiter(self, waiter: _Waiter, *, timed_out: bool) -> None:
        with self._lock:
            st = self._state[waiter.scheduling_class]
            if waiter in st.waiters:
                st.waiters.remove(waiter)
                if timed_out:
                    st.timed_out += 1
                return
        # Der Slot wurde bereits fuer diesen Waiter reserviert -> zurueckgeben.
        self._release_one(waiter.scheduling_class)

    def _release_one(self, cls: SchedulingClass) -> None:
        with self._lock:
            st = self._state[cls]
            st.active = max(0, st.active - 1)
            while st.waiters:
                waiter = st.waiters.popleft()
                if waiter.future.done() or waiter.loop.is_closed():
                    continue
                # Slot wird hier reserviert (nicht erst beim Aufwecken), damit
                # ein paralleler try_acquire nicht dazwischengreifen kann.
                st.active += 1
                waiter.loop.call_soon_threadsafe(_fulfil_waiter, waiter.future)
                break

    def release(self, lease: BulkheadLease) -> None:
        """Gibt den Slot eines gewaehrten Lease frei (idempotent)."""
        if not lease.granted or lease._released:
            return
        lease._released = True
        self._release_one(lease.scheduling_class)

    def backpressure(self, scheduling_class: Any) -> Dict[str, Any]:
        """Backpressure-Signal einer Klasse (Diagnose/Rejection-Header)."""
        cls = normalize_scheduling_class(scheduling_class)
        cfg = self._configs.get(cls, DEFAULT_BULKHEAD_CONFIGS[cls])
        with self._lock:
            st = self._state[cls]
            active = st.active >= cfg.capacity or len(st.waiters) >= cfg.max_queue
            return {
                "scheduling_class": cls,
                "backpressure_active": active,
                "active": st.active,
                "queued": len(st.waiters),
                "capacity": cfg.capacity,
                "max_queue": cfg.max_queue,
                "retry_after_seconds": self._retry_after,
            }

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Zaehlstaende je Klasse; keine Secrets, keine Task-Inhalte."""
        with self._lock:
            out: Dict[str, Dict[str, Any]] = {}
            for cls in SCHEDULING_CLASSES:
                st = self._state[cls]
                cfg = self._configs.get(cls, DEFAULT_BULKHEAD_CONFIGS[cls])
                out[cls] = {
                    "capacity": cfg.capacity,
                    "max_queue": cfg.max_queue,
                    "active": st.active,
                    "queued": len(st.waiters),
                    "admitted": st.admitted,
                    "rejected": st.rejected,
                    "timed_out": st.timed_out,
                    "backpressure_active": (
                        st.active >= cfg.capacity or len(st.waiters) >= cfg.max_queue
                    ),
                }
            return out

    def reset(self) -> None:
        """Nur fuer Tests/Diagnose: Zaehlstaende leeren, Konfiguration bleibt."""
        with self._lock:
            self._state = {cls: _ClassState() for cls in SCHEDULING_CLASSES}


scheduling_bulkheads = SchedulingBulkhead()

__all__ = (
    "SCHEDULING_CLASSES",
    "SchedulingClass",
    "BulkheadConfig",
    "BulkheadLease",
    "BulkheadRejected",
    "SchedulingBulkhead",
    "DEFAULT_BULKHEAD_CONFIGS",
    "normalize_scheduling_class",
    "load_bulkhead_configs",
    "set_scheduling_class",
    "current_scheduling_class",
    "scheduling_bulkheads",
)
