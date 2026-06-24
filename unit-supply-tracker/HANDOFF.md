# HANDOFF — Unit Supply & Rations Tracker

**Project:** Private, invite-only mobile app for a 92Y Unit Supply Specialist
**Unit:** C Battery, 2-218th FA
**Status:** Code complete + tested. Not yet in its own repo or built. See "Open items."
**Owner:** Jason Dixon (CreatorJD1 / jasondixon1994@gmail.com)

---

## 1. What this is

A native mobile app (Expo / React Native) backed by a cloud database (Supabase)
that replaces paper/spreadsheet accountability for the supply section. It tracks:

- **Master roster** (battalion-scoped) — rank, last name, first initial, section,
  duty status. **No SSN / DoD ID stored, by design.**
- **Live per-section headcount board** — GUN 1, GUN 2, GUN 3, AMMO, FDC,
  HEADQUARTERS, with a battery present/assigned **TOTAL**. Updates live across
  phones.
- **Rations control** — headline **TOTAL MREs on hand**, days of supply, one-tap
  **chow count** per section (auto-deducts MREs from stock), 7-day burn rate,
  low-stock alert, and a whole-case **resupply suggestion**.
- **PERSTAT** — strength rollup with absent-by-reason remarks, **shareable as CSV**
  up the chain.

**Access model:** invite-only. No public sign-up. Accounts are created by the
supply clerk / supply sergeant. Row-Level Security (RLS) locks every row to the
unit; section chiefs can only edit their own section's counts.

---

## 2. Where the code is RIGHT NOW

The complete project lives in the folder **`unit-supply-tracker/`** on this branch:

- **Repo:** `github.com/CreatorJD1/alpaccaai`
- **Branch:** `claude/military-supply-tool-review-rxrk0h`
- **Pull request:** **#5** (draft) — `github.com/CreatorJD1/alpaccaai/pull/5`

> It was placed inside `alpaccaai` only because the build session was locked to
> that one repo and could not push to a new repo. It is a fully standalone project
> (its own `package.json`, tests, README) and is meant to live in its own repo.

---

## 3. Move it into its own repo `SUPPLY-TOOL` (needs a PC, ~1 min)

An empty repo already exists at `github.com/CreatorJD1/SUPPLY-TOOL`. On any
computer with git:

```bash
git clone https://github.com/CreatorJD1/alpaccaai.git
cd alpaccaai
git checkout claude/military-supply-tool-review-rxrk0h
cd unit-supply-tracker
git init && git add -A && git commit -m "Initial commit: Unit Supply & Rations Tracker"
git branch -M main
git remote add origin https://github.com/CreatorJD1/SUPPLY-TOOL.git
git push -u origin main
```

This puts `package.json`, `app/`, `lib/`, `supabase/` at the repo root — correct.

*(Phone-only alternative: just merge PR #5 and use it from inside `alpaccaai`.)*

---

## 4. Stand it up so it actually runs (needs a PC)

Full steps are in `unit-supply-tracker/README.md`. Summary:

### a. Supabase (the cloud backend) — free tier
1. Create a project at https://supabase.com.
2. SQL editor → run `supabase/migrations/0001_init.sql`, then `supabase/seed.sql`
   (creates C/2-218th FA, its six sections, and an MRE inventory row).
3. **Auth → Providers → Email → turn OFF "Enable email signups."** This is the
   invite-only switch.

### b. Invite your people
1. Auth → Users → **Invite** (you, supply sergeant, each section chief).
2. Attach each to the unit with a role by inserting a `profiles` row (commented
   example at the bottom of `seed.sql`). Roles: `supply_clerk`, `supply_sergeant`,
   `section_chief` (+ their `section_id`), `viewer`.

### c. Run / build
```bash
cp .env.example .env        # paste your Supabase URL + anon key
npm install
npm test                    # 11 accountability-math tests should pass
npm start                   # open in Expo Go on your phone to try it
```
Installable Android app:
```bash
npm install -g eas-cli
eas login
eas secret:create --name EXPO_PUBLIC_SUPABASE_URL --value <your url>
eas secret:create --name EXPO_PUBLIC_SUPABASE_ANON_KEY --value <your anon key>
eas build -p android --profile preview      # produces an installable APK
```
iOS needs an Apple Developer account (`eas build -p ios`).

---

## 5. Tech + layout (for whoever maintains it)

- **Frontend:** Expo / React Native + TypeScript, expo-router navigation.
- **Backend:** Supabase (Postgres + Auth + Realtime). No server to operate.
- **Security:** RLS on every table (`supabase/migrations/0001_init.sql`). The
  shipped anon key reads nothing without an invited, unit-scoped account.

```
unit-supply-tracker/
  app/(auth)/sign-in.tsx      invite-only login (no sign-up button)
  app/(tabs)/index.tsx        Headcount Board (live)
  app/(tabs)/roster.tsx       Master roster + duty status editor
  app/(tabs)/rations.tsx      MRE inventory, chow count, days-of-supply, resupply
  app/(tabs)/perstat.tsx      Strength rollup + CSV share
  app/(tabs)/settings.tsx     role, OPSEC notice, sign out
  lib/calc.ts                 PURE accountability math (unit-tested)
  lib/queries.ts              all Supabase reads/writes (unit-scoped)
  lib/session.tsx             auth + role context (no profile => no access)
  lib/useUnitData.ts          live roster loader (Realtime subscription)
  supabase/migrations/        schema + RLS policies
  supabase/seed.sql           C/2-218th FA + sections seed
  __tests__/calc.test.ts      11 Jest tests
```

**Data model:** `units → sections → soldiers`; plus `profiles` (user→unit+role),
`ration_inventory` (MRE: cases × 12 + loose meals + reorder point),
`ration_counts` (per-section chow logs), `headcount_log`.

**Key math (all in `lib/calc.ts`, all tested):** section rollup, meals-on-hand,
days-of-supply, 7-day burn rate, low-stock, suggested resupply cases, immutable
MRE deduction, PERSTAT CSV.

---

## 6. Test status

`npm test` → **11/11 passing** (rollups, days-of-supply, burn rate, low-stock,
immutable MRE deduction, resupply rounding, CSV export). Run from the project root.

---

## 7. OPSEC notes (read before fielding)

- A unit roster is **CUI/FOUO**. The app stores the minimum (name + rank + section
  + status) and scopes every row to the unit, but it is hosted on commercial cloud
  (Supabase). **Confirm this is acceptable under your unit's policy** before real
  use.
- Do **not** enter SSNs, DoD IDs, contact info, or anything classified. The
  Settings screen shows this reminder in-app.

---

## 8. Open items / next steps

1. **Move code to `SUPPLY-TOOL`** (section 3) — or merge PR #5.
2. **Create Supabase project + run migrations** (section 4a).
3. **Invite users** (section 4b).
4. **EAS build** the installable app (section 4c).
5. **Roadmap (designed-for, not yet built):** push suspense reminders, offline
   field mode with sync, Class I burn chart, audit-trail view, extension to other
   supply classes / sensitive-item quick counts. None require schema rewrites.

---

## 9. Why some steps need a PC

Phone-only is fine for **using** the finished app, and for **merging PR #5**. But
**creating the Supabase project**, **moving the repo**, and **building the APK with
EAS** are developer steps that need a computer once. After the APK is built and
distributed, day-to-day use is entirely on phones.
