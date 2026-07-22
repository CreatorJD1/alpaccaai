# Phase 7 Pagefile Telemetry

`alpecca.pagefile_telemetry.collect_pagefile_telemetry()` is an isolated,
read-only Windows observation primitive. It is not wired to the server,
approval ledger, scheduler, UI, or any execution helper.

The result contains only aggregate MiB facts:

- configuration mode (`system_managed`, `custom`, `none`, or `unknown`);
- configured initial and maximum size when fixed settings are observable; and
- allocated, currently used, free, and peak-used pagefile capacity.

Sizes are aggregate totals across bounded configuration or active-usage rows;
each fact group includes its aggregate `entry_count`.

`evidence.powershell` and `evidence.wmi` explicitly distinguish available,
partial, invalid, timed-out, and unavailable evidence. Unknown values remain
`null`; they are never converted to zero. Non-Windows hosts return one stable
`non_windows` unavailable result without spawning a process.

The collector runs one encoded, code-owned query from the kernel-reported
Windows system directory. The process is capped at five seconds, each CIM
class is capped at 16 rows, and output above 8 KiB is rejected. The query
selects and returns no pagefile path, computer name, user, process, device, or
error text.

This module cannot accept a command, request elevation, change pagefile or
registry settings, or grant execution authority. Any later use of the facts
still requires fresh observation, the separate one-use CreatorJD approval,
and an independently reviewed execution boundary.
