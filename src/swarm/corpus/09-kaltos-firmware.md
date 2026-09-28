---
doc_id: doc-09
title: "KaltOS 4.2 Control Firmware Release Notes"
date: "2025-08-19"
tags: [kaltos, firmware, controls]
---

# KaltOS 4.2 Control Firmware Release Notes

KaltOS 4.2 is the current stable control firmware for the K-Series and ships preinstalled on all units built since May 2025. Units on KaltOS 4.0 or 4.1 receive the update automatically over the air in staged waves; upgrades from the 2.x and 3.x series are performed by a certified partner because they replace the control module bootloader.

Highlights in 4.2. The modulation controller for the XK-7 compressor module was retuned with a model-predictive speed profile, reducing short-cycling in low-load conditions by about 40 percent in the field trial fleet. Weather-compensation curves are now learned per building over the first three heating seasons instead of being fixed from commissioning data alone.

Diagnostics. KaltOS 4.2 exposes a per-module health ledger: runtime hours, start counts, inverter temperature histograms, and acoustic screening fingerprints recorded at the factory. Service partners can compare a field module's vibration and sound signature against the factory reference for the same serial number, which shortens fault-tracing visits.

Security. The local API now requires signed tokens for write operations, and the cloud telemetry path uses certificate pinning. A responsible-disclosure programme is linked from the product website, and critical fixes are backported to the 4.x line for a minimum of five years.

Rollout status. As of the release date, roughly 60 percent of the connected fleet runs the 4.2 line. Partners are advised to complete the free online training module before servicing 4.2 units, since several commissioning screens were reorganised. Release notes for every intermediate build are available in the partner portal archive.
