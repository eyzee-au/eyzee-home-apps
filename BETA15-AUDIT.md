# Beta.15 Core release audit

## Diagnostic correction

Changed-file update failures include the managed relative path in both the
failure message and support report. The updater still stops before backup or
write operations and preserves all existing files.

Core migration also accepts the exact unrendered file from the verified signed
release as a safe baseline. This permits deterministic Home-to-Core rendering
without weakening protection for any genuinely modified local file.

The only beta14 managed source that changed in beta15 is
`eyzee/ui/living/eyzee-main-menu.yaml`. Setup accepts its exact official beta14
SHA-256 (`c30adc34f471e069bac911b24cecfeeb55527faef6b8612f8360e61d4b10500f`)
for that path only. All other byte values still stop before backup or writes.
The verified current hash is passed into the atomic writer so its second safety
check recognises the same approved file. A change occurring after preflight is
still refused and rolled back.

For Core upgrades, Setup also migrates the exact beta14 inline Lovelace
registration title from `EyZEE® Home` to `EyZEE® Core`. It preserves comments,
other dashboards and all unrelated configuration. Custom titles are left
untouched. The original `configuration.yaml` is included in the update journal
and restored automatically if Home Assistant validation fails.

Archive: `EyZEE-Core-0.1.0-beta.15.zip`
Checks: **42/42 passed**

The signed package is edition-neutral and is rendered from the activated
entitlement plan. This audit renders the Core edition with the installer's
rule. On a fresh install only, `eyzee/state/rooms.yaml` is edition-rendered
so Core starts with `project: My EyZEE Core`; every other generated state
file and the generated/mutable UI pages are copied raw.

| Check | Result | Detail |
| --- | --- | --- |
| Release version is 0.1.0-beta.15 | PASS | 0.1.0-beta.15 |
| Required Setup version is 0.1.0-beta.15 | PASS | 0.1.0-beta.15 |
| Archive has no duplicate entries | PASS | 92 entries |
| Archive is release.json + payload-hashes.json + hashed payload | PASS | 92 files |
| All payload SHA-256 hashes match | PASS | 90 files, 0 bad |
| Managed updates include eyzee/dashboards.yaml | PASS |  |
| Managed updates include eyzee/ui/living/eyzee-main-menu.yaml | PASS |  |
| Managed updates include eyzee/ui/eyzee-onboarding.yaml | PASS |  |
| Managed updates include eyzee/ui/setup/eyzee-setup.yaml | PASS |  |
| Managed updates exclude eyzee/ui/eyzee-room.yaml | PASS |  |
| Managed updates exclude eyzee/ui/eyzee-master.yaml | PASS |  |
| Managed updates exclude eyzee/ui/setup/add_device.yaml | PASS |  |
| Managed updates exclude eyzee/ui/setup/device_setup.yaml | PASS |  |
| Managed updates exclude eyzee/state/rooms.yaml | PASS |  |
| Managed updates exclude eyzee/generated_smart_behaviours.yaml | PASS |  |
| Core page title is EyZEE® Core | PASS | dashboards.yaml |
| Core main menu title is EyZEE® Core | PASS | title: EyZEE® Core |
| Core visible heading is EyZEE Core | PASS |  |
| Core theme name is EyZEE Core | PASS | EyZEE Core: |
| Updates & Support route is present | PASS |  |
| No local test add-on slug in the production dashboard | PASS |  |
| Internal identifier preserved: /eyzee-home/ | PASS | 61 occurrences |
| Internal identifier preserved: eyzee_home | PASS | 5 occurrences |
| Internal identifier preserved: eyzee-main-menu | PASS | 131 occurrences |
| Internal identifier preserved: eyzee-house-builder | PASS | 14 occurrences |
| Internal identifier preserved: eyzee-room | PASS | 16 occurrences |
| Internal identifier preserved: eyzee-setup | PASS | 5 occurrences |
| Internal identifier preserved: eyzee-add-device-new | PASS | 14 occurrences |
| No unintended visible EyZEE Home labels in rendered product files | PASS |  |
| Generated homeowner state not edition-rendered: payload/config/eyzee/generated_smart_behaviours.yaml | PASS |  |
| Generated homeowner state not edition-rendered: payload/config/eyzee/templates/fans.yaml | PASS |  |
| Fresh Core rooms.yaml project is My EyZEE Core | PASS |  |
| Fresh Home rooms.yaml project is My EyZEE Home | PASS |  |
| rooms.yaml is outside managed updates | PASS |  |
| Mutable UI page is outside managed updates and rendered only on first install: payload/config/eyzee/ui/eyzee-master.yaml | PASS |  |
| Mutable UI page is outside managed updates and rendered only on first install: payload/config/eyzee/ui/eyzee-room.yaml | PASS |  |
| Mutable UI page is outside managed updates and rendered only on first install: payload/config/eyzee/ui/setup/add_device.yaml | PASS |  |
| Mutable UI page is outside managed updates and rendered only on first install: payload/config/eyzee/ui/setup/device_setup.yaml | PASS |  |
| No populated room records in the package | PASS |  |
| No populated device records in the package | PASS |  |
| No installation, subscription or credential state files | PASS |  |
| No private signing keys | PASS |  |

## Fresh-install and preservation rules

- `payload/config/eyzee/state/rooms.yaml` is rendered only when it does not
  already exist: Core gets `project: My EyZEE Core`; Home keeps
  `project: My EyZEE Home`.
- An existing customer-edited `rooms.yaml` is preserved byte-for-byte.
- `rooms.yaml` remains excluded from managed updates, as do all other
  generated homeowner state files.
- The four generated/mutable UI pages are excluded from managed updates and
  are rendered only when first created on a fresh install.
