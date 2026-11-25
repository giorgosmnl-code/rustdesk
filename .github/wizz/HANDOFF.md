# RustDesk Multiview: handoff notes

Read this before working on the app. It covers how George's custom RustDesk
Android app is built and where things stand.

## What this is

- **Repo:** `giorgosmnl-code/rustdesk`, a fork of the official RustDesk.
- **The app:** "RustDesk Multiview" (`com.wizz.rustdesk.multiview`), an Android
  client for George's self-hosted RustDesk server. It can open several PCs at
  once (sessions strip, background sessions) and has many extras.
- **A second variant**, "RustDesk Wizz" (`com.wizz.rustdesk`), is the same
  patch with multi-session off. It's hardly used.
- **Server:**
  - Hetzner VPS 116.203.56.80 (hbbs/hbbr)
  - lejianwen/rustdesk-api on port 21114 for login and the address book
  - Key: `1NoyO50yYCajlCMJjeMQvyAfAy9dB675OaMTlsMEcvY=`

## How the code is organised

- **All app changes live in one Python script, `.github/wizz/wizz_apply.py`.**
  At build time it patches the upstream sources: Dart, Kotlin and Gradle.
  Upstream files are never edited directly in the repo.
- **`.github/wizz/wizz_rust.py`** holds the small Rust-side patches.
- **Helpers inside `wizz_apply.py`:**
  - `load(p)` / `save(p, s)`
  - `rep(s, old, new, count=1)` asserts the match count, so a stale anchor
    fails loudly.
  - `kt` is the Kotlin package path prefix.
- **Embedded Dart files** are written out early as raw strings:
  - `WIZZ_SESSIONS_DART`: multi-session host, connect, close-all, exit
  - `WIZZ_SWITCHER_DART`: toolbar, sessions strip, previews, keyboard fan,
    screenshot
  - `WIZZ_SETTINGS_DART`: `WizzPrefs` (local options `wizz-*`), all
    settings pages, skins, server profiles, backup/restore, extra keys,
    real-keys and paste helpers
- **Later "part" sections**, one per build, are appended before the final
  `print('wizz multi-session patch applied')`. Each one patches the generated
  files with `rep()`.
- **To test locally:** copy a clean upstream tree, put the script at
  `.github/wizz/wizz_apply.py`, then run
  `WIZZ_VARIANT=multiview python3 .github/wizz/wizz_apply.py`. It must print
  the final line without an assertion. Then check bracket balance of the
  changed Dart files. There's no Flutter SDK locally, so CI is the compiler.
- **Toolchain:** Flutter 3.24.5 / Dart 3.x.
  - Use `WillPopScope`, not `PopScope`.
  - `MyTheme.accent` is const, so the theme goes through `wizzSkinTheme()`.

## Build and delivery (no PC needed)

1. The Claude GitHub App is installed on the account, so a session can
   `git push` directly.
2. **A push to `master` that changes `.github/wizz/wizz_apply.py`,
   `wizz_rust.py` or `wizz-android.yml` builds the multiview APK by itself**
   (workflow `.github/workflows/wizz-android.yml`, about 10 minutes when the
   Rust cache hits).
3. The finished APK is force-pushed to the branch **`apk-multiview`** as
   `rustdesk-multiview.apk`, plus a `.sha256` file. Fetch it with
   `git fetch --depth=1 origin apk-multiview` and
   `git show FETCH_HEAD:rustdesk-multiview.apk > out.apk`, check the sha256,
   then send it to George.
4. Actions artifacts can't be downloaded through the session proxy, which is
   why the apk branch exists. `gh workflow run` also fails through the proxy,
   which is why builds run on push.
5. If a build fails with Maven "429 Too Many Requests", re-run it
   (`gh run rerun <id> --failed`). It's not a code error.

## George's rules

- **Don't build or push to `master` without his explicit go ("build").**
  Push to `master` = build. Keep work in progress on the `wizz-next` branch.
- "Discuss" or "discuss only" means answer only, no code changes.
- Scripts for café PCs are CMD/batch, run hidden through Gizmo.
- Never type passwords, keys or tokens into fields for him.

## State as of build #22 (25 Nov 2026)

Delivered up to #22. The `wizz-next` branch has the next build ready, not yet
built:

- **Win key:** a tap while it's lit only switches it off. Previously the tap
  also sent Win.
- **Start-up PCs:**
  - Chosen from a PC's ⋮ menu ("Open on app start") or from Settings →
    Multiview → Start-up PCs (Add PC, reorder, remove).
  - They connect straight away on a fresh app start, after the app lock.
  - The list is included in backups.

### Parked ideas (only when George asks)

- Send the phone clipboard to a PC when it finishes connecting. Android
  RustDesk has no initial clipboard sync.
- Optional saved passwords in backups, encrypted with a backup PIN. Needs a
  Rust FFI change to write the peer password hash.
- Auto keyboard on text fields (I-beam cursor detection).
- Radial menu for other toolbar buttons, copy to all PCs, JetKVM integration.
- Settings grouping and pruning.

### Known decisions

- The dynamic toolbar (#20) was reverted in #21. Keep the #19 even-spaced row.
- Long press stays right click. Tap-then-drag is adjustable in Mouse settings.
- Real key presses are per PC (map keyboard mode + USB HID codes). They're
  for Gizmo's remote viewer, which turned "6" into "*".
- Auto-close works in the background only: default 15 min, a 60 s warning
  with "Keep connected", file transfers postpone it, and it exits the app
  completely.
- Backups contain no passwords. The PC list is included from #21.
