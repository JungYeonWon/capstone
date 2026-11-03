# Isolated cloud deployment

## Git deployment update — 2026-11-03

The repository was transferred to `https://github.com/JungYeonWon/capstone`.
The existing Vercel `capstone-cloud` project is connected to that repository,
with `main` as its production branch. Pushes to `main` trigger Vercel builds;
successful production builds update `https://capstone-cloud.vercel.app`.
The GitHub Vercel app is scoped to the `capstone` repository.

Database schema migrations must be reviewed and applied separately before any
code that depends on them is released. Git deployment does not migrate the
Supabase database or rotate encryption keys. Existing production secrets stay
in Vercel and must never be committed. Non-production branches do not receive
production database credentials automatically.

The initial-isolation notes below describe the original setup, before the
owner authorized using a single shared `main` branch.

The original `capstone` checkout and existing cloud projects must not be modified.
This checkout was cloned locally without secrets, database files, or uploaded documents.
Its original Git remote was removed to prevent accidental pushes to the original repository.

## Newly created resources

- Vercel project: `capstone-cloud`
- Vercel project ID: `prj_MOKJpG2rG5xHg23QxYURxzzMgKN1`
- Vercel team ID: `team_PDkTmmmovA0k2wcVfdaPHwkq`
- Supabase project: `capstone-cloud`
- Supabase project reference: `brfbodknasswtevhsbme`
- Supabase organization: `DRoda` (`gwxnlnimmhrtevwmngki`)
- Supabase region: `ap-northeast-2` (Seoul)

## Current status

Cloud application has been deployed using Vercel Services (Beta): Next.js at `/`
and FastAPI at `/api/v1`. Both run in the same isolated project.
Production alias: https://capstone-cloud.vercel.app
Check the latest deployment and the verification report before declaring it usable.
No existing users or private documents were imported.

## Required private configuration

After the owner's explicit permission, the setup created a restricted `capstone_api`
database login, with DML access only to a private `capstone` schema. All application
tables have RLS enabled and an explicit backend-role policy. The schema is not
exposed to the Supabase Data API. Existing application login and owner checks remain
in FastAPI; this version does not use Supabase Auth.

- `DATABASE_URL`: new project only, transaction pooler, stored as a Production Secret.
- `SECRET_KEY`: generated signing key, stored as a Production Secret.
- `DATABASE_SCHEMA=capstone`, `CLOUD_MODE=1`, `NEXT_PUBLIC_API_URL=/api/v1`.
- No Supabase service-role key was retrieved or used.
- TLS uses `verify-full` with the public CA from the Supabase dashboard, stored at
  `server/certs/supabase.crt` (this certificate is public, not a credential).

## Free demo scope

- Original uploads are stored as small binary values in the private Supabase DB,
  not in a public bucket. This avoids provisioning or copying a broad admin key.
- 3 MB per upload; 20 active files per user; 100 MB shared application file quota.
  The quota is serialized with a transaction advisory lock.
- Temporary working files are cleaned after each response; a cold function can
  retrieve an original from the database. Expired files cannot be downloaded even
  before the next purge.
- HWPX, DOCX and PDF uploads are supported. Legacy HWP conversion and native
  HWP/HWPX-to-PDF previews require Windows/Hancom and are unavailable in this build.
- All nine built-in forms retain native output and PDF/page previews.
- AI defaults to local rules; SMTP defaults to mock. No paid AI or email provider
  was connected. No paid hosting plan or add-on was activated.
- This is a student demonstration deployment, not an audited production system.
  Avoid entering real sensitive information. Hosting free-tier limits still apply.

## Verification and updates

`scripts/smoke_cloud.py <origin>` creates disposable fictional users, checks user
isolation, nine native/PDF/preview outputs, and persistent upload/autofill.
It prints disposable user IDs for a narrowly scoped cleanup, never passwords/tokens.

`scripts/deployment_sources.py` emits only an allowlisted set of application source,
the base HWPX asset and public CA. It excludes secrets, local DB, user uploads and
test documents. The Korean font is fetched from Google Fonts during the build,
with its SHA-256 verified and the OFL license retained.
