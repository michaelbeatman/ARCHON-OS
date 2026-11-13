---
name: skill-lagerbestand-working-capital
description: Sicherheitsbestands-Formeln, Meldebestands-Berechnung, ABC/XYZ-Analyse und Reduktion von Kapitalbindung.
version: 1.0.0
author: ARCHON OS Intelligence
category: 2. Handel, Beschaffung & E-Commerce
tags: ["lager", "working-capital", "sicherheitsbestand", "bestand"]
---

# 🏭 Lagerbestands- & Working-Capital-Optimierung

Ausbalancierung von Lieferfähigkeit (Service Level) und Liquiditätsschonung.

## 1. Sicherheitsbestand-Formel
$$SB = z \cdot \sigma_L \cdot \sqrt{L}$$
- $z$: Sicherheitsfaktor (z. B. 1,65 für 95% Servicegrad).
- $\sigma_L$: Standardabweichung des täglichen Verbrauchs.
- $L$: Wiederbeschaffungszeit in Tagen.

## 2. ABC/XYZ-Klassifizierung
- **AX-Artikel:** Hoher Wert, stetiger Verbrauch -> Just-in-Time Beschaffung.
- **CZ-Artikel:** Geringer Wert, unregelmäßiger Verbrauch -> Großmengen oder Konsignation.
