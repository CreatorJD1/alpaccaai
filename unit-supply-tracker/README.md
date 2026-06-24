# Unit Supply & Rations Tracker

A **private, invite-only** mobile app for a 92Y Unit Supply Specialist. Built for
**C Battery, 2-218th FA** to replace paper/spreadsheet accountability with a phone
in every section's pocket.

It tracks:

- **Master roster** (battalion-scoped) — rank, last name, first initial, section,
  duty status. *No SSN, no DoD ID — by design.*
- **Per-section troop count** — live tiles for **GUN 1 / GUN 2 / GUN 3 / AMMO /
  FDC / HEADQUARTERS** with a battery present/assigned **TOTAL**.
- **Rations control** — headline **TOTAL MREs on hand**, days of supply, low-stock
  alert, one-tap **chow count** per section (auto-deducts MREs), 7-day burn rate,
  and a whole-case **resupply suggestion**.
- **PERSTAT** — strength rollup with absent-by-reason remarks, **shareable as CSV**
  up the chain.

## Why these choices

- **Native app:** Expo / React Native (one codebase, Android + iOS), distributed
  privately via EAS — never listed in an app store.
- **Cloud, no server to run:** Supabase (Postgres + Auth + Realtime). The board
  updates live across phones via Realtime.
- **Private & locked down:** every table is behind Row-Level Security. The shipped
  anon key reads **nothing** without an invited, unit-scoped account. Section
  chiefs can only write **their own** section's headcount/chow counts.

## OPSEC

A unit roster is **CUI/FOUO**. This app deliberately stores the minimum (name +
rank + section + status) and scopes every row to your unit. Do **not** enter SSNs,
DoD IDs, contact info, or anything classified. Confirm cloud hosting of even this
data is acceptable under your unit's policy before fielding it.

## Setup

### 1. Supabase project
1. Create a free project at <https://supabase.com>.
2. In the **SQL editor**, run `supabase/migrations/0001_init.sql`, then
   `supabase/seed.sql` (creates C/2-218th FA and its six sections + an MRE
   inventory row).
3. **Auth → Providers → Email:** turn **OFF** "Enable email signups" so no one can
   self-register. This is the invite-only guarantee.

### 2. Invite yourself (and your section)
1. **Auth → Users → Invite user** for each person (you, supply sergeant, section
   chiefs).
2. Attach each invited user to the unit with a role by inserting a `profiles` row
   (see the commented example at the bottom of `supabase/seed.sql`). Roles:
   `supply_clerk`, `supply_sergeant`, `section_chief` (set their `section_id`),
   `viewer`.

### 3. App config
```bash
cp .env.example .env       # fill in EXPO_PUBLIC_SUPABASE_URL + _ANON_KEY
npm install
npm test                   # verify the accountability math (11 tests)
npm start                  # open in Expo Go on your phone
```

### 4. Build the installable app
```bash
npm install -g eas-cli
eas login
eas build -p android --profile preview     # installable APK
# iOS: eas build -p ios --profile preview   (needs an Apple developer account)
```
Put your Supabase values into EAS:
`eas secret:create --name EXPO_PUBLIC_SUPABASE_URL --value ...` (and the anon key).

## Project layout

```
app/                 expo-router screens
  (auth)/sign-in     invite-only login (no sign-up button)
  (tabs)/index       Headcount Board (live)
  (tabs)/roster      Master roster + duty status
  (tabs)/rations     MRE inventory, chow count, days-of-supply, resupply
  (tabs)/perstat     Strength rollup + CSV share
  (tabs)/settings    role, OPSEC notice, sign out
lib/calc.ts          PURE accountability math (unit-tested)
lib/queries.ts       all Supabase reads/writes (unit-scoped)
lib/session.tsx      auth + profile/role context (no profile => no access)
supabase/            schema, RLS policies, seed for C/2-218th FA
__tests__/calc.test  Jest tests for the math
```

## Roadmap (built to extend)

The math, channels, and role model are in place for the next ideas from planning:
push **suspense reminders**, **offline field mode** with sync, a **Class I burn
chart**, an **audit trail** view, and extension to other classes of supply /
sensitive-item quick counts. None require schema rewrites.

---
*Private tool for the supply section. Not for public use.*
