# PCIP Setup Guide — every credential, every link, exactly what to do

Work through the phases in order. Only **Phase 0–2 are required** to get
value (Canva + graph + copy); everything after is optional and can be added
any time — unconfigured providers simply drop out of routing, and
`python -m pcip status` always shows what's live.

---

## Phase 0 — Install (5 min)

```bash
git clone https://github.com/hendry-architect/ai-mazing.git
cd ai-mazing
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # you will fill this in below
```

After each phase below, re-check status:

```bash
python -m pcip status
```

You do **not** need to export anything — PCIP reads `.env` itself on every
run. Avoid the `export $(grep ... | xargs)` idiom in particular: `xargs`
splits on whitespace, so it mangles any value containing a space (a
WordPress Application Password, for one), and an exported empty variable
outranks the file and produces an authentication error that looks nothing
like "this one is blank".

---

## Phase 1 — Canva Connect API (required, ~15 min, no Enterprise needed)

**Docs:** <https://www.canva.dev/docs/connect/> ·
**Scopes reference:** <https://www.canva.dev/docs/connect/appendix/scopes/> ·
**OAuth guide:** <https://www.canva.dev/docs/connect/authentication/>

> **Plan note:** a **public integration in development mode** works fully
> for your own account with no review submission and no Enterprise plan.
> Enterprise is only required for *private* integrations and the
> brand-template/autofill APIs — `pcip doctor --live` reports those as
> `not_entitled` until then, and everything else works.

1. Sign in to Canva, open the Developer Portal:
   <https://www.canva.com/developers/> → **Your integrations** →
   **Create an integration** → choose **Public**. Name it `PCIP`.
   Do **not** submit it for review — development mode is exactly what we want.
2. On the integration's **Scopes** tab, enable:
   `design:meta:read`, `design:content:read`, `design:content:write`,
   `folder:read`, `asset:read` (+ `brandtemplate:meta:read`,
   `brandtemplate:content:read` if the portal offers them on your plan).
3. On **Configuration**: copy the **Client ID**, click **Generate secret**
   (shown once) → `.env` → `CANVA_CLIENT_ID`, `CANVA_CLIENT_SECRET`.
4. Under **Redirect URLs**, add the callback. A **private** integration can
   use `http://127.0.0.1:8080/callback`; a **public** one cannot — Canva
   requires a non-localhost URL to review it, so use
   `https://passqual.com/canva/callback`.
5. Run the OAuth helper. Which form depends on the redirect you registered.

   **Localhost redirect** — one command; it opens the consent screen, catches
   the callback, exchanges the code, and writes the tokens into `.env`:

   ```bash
   python -m pcip canva-auth
   ```

   **Hosted redirect** — the code lands in a browser rather than on this
   machine, so it comes back in two steps:

   ```bash
   python -m pcip canva-auth --redirect-uri https://passqual.com/canva/callback --start
   # authorize in the browser, then select the address bar (Cmd-A, Cmd-C)
   pbpaste | python -m pcip canva-auth --finish
   ```

   The two steps exist because of the terminal, not the protocol: macOS gives
   a tty a **1024-byte** canonical input buffer, and Canva issues the
   authorization code as a JWT that makes the redirect URL longer than that.
   Pasted at an interactive prompt it silently does nothing — Return never
   submits the line. A pipe has no such limit. `--code-file <path>` works
   too, and keeps the code out of shell history.

   The callback page itself will 404 (nothing serves that route on
   passqual.com). That is expected — the code is in the address bar either
   way. `--start` writes the flow's PKCE verifier to
   `pcip_data/canva_auth_pending.json` (mode 600) and `--finish` deletes it;
   an authorization older than 15 minutes is refused, since Canva codes are
   good for about ten.

6. Verify and run your first sync:

   ```bash
   python -m pcip init
   python -m pcip doctor --live          # canva should report ready
   python -m pcip sync                   # mirrors designs/folders → graph
   python -m pcip search "logo"          # prove the graph is live
   ```

PCIP refreshes the access token automatically from then on (Canva rotates
refresh tokens on every refresh; the client keeps up).

---

## Phase 2 — Claude copy generation (required for copy, ~5 min)

**Console:** <https://console.anthropic.com/> ·
**Docs:** <https://docs.anthropic.com/>

1. Console → **API keys** → **Create key** → `.env` → `ANTHROPIC_API_KEY`.
2. Optional: change `PCIP_ANTHROPIC_MODEL` (default `claude-sonnet-5`).

---

## Phase 3 — WordPress → passqual.com (~15 min)

**Application Passwords docs:**
<https://wordpress.org/documentation/article/application-passwords/> ·
**REST API docs:** <https://developer.wordpress.org/rest-api/>

### How an article actually reaches passqual.com

passqual.com is a Next.js site on Vercel. It does **not** store articles — it
fetches them from WordPress on each request and caches the result for 60
seconds. So:

```
pcip publish → WordPress (wp.passqual.com) → passqual.com/<slug>/  ≈60s later
```

No deploy, no developer, no route file. That also means **two hostnames**, and
they are not interchangeable:

| Variable | Host | Why |
|---|---|---|
| `WORDPRESS_URL` | `https://wp.passqual.com` | where the REST API lives — writes go here |
| `WORDPRESS_PUBLIC_SITE` | `https://passqual.com` | where readers land — the URL PCIP records |

Pointing `WORDPRESS_URL` at the public site cannot work: that site deliberately
rewrites `/wp-json/*` to a blocked route.

Marketing, service and team pages are **not** WordPress-driven — they are
hand-authored modules in the website repository. PCIP publishes articles only,
and `pcip can wordpress.edit_live_page` reports `unsupported` to say so.

### Steps

1. On **wp.passqual.com** → WP Admin → **Users → Profile** → **Application
   Passwords**. Name it `PCIP`, **Add New Application Password**, copy it
   (shown once — it contains spaces; keep them).
2. `.env`:
   ```
   WORDPRESS_URL=https://wp.passqual.com
   WORDPRESS_PUBLIC_SITE=https://passqual.com
   WORDPRESS_USER=<wp username>
   WORDPRESS_APP_PASSWORD=<generated password>
   ```
   *(WordPress.com-hosted sites instead use `WORDPRESS_COM_TOKEN` from
   <https://developer.wordpress.com/apps/>.)*
3. **Prerequisite on SiteGround — restore the `Authorization` header.**
   SiteGround strips it before PHP, so Application Passwords return
   `401 rest_not_logged_in` and **no publish can succeed** until this is added.
   Site Tools → File Manager → edit `.htaccess` in the document root, *above*
   `# BEGIN WordPress`:
   ```apache
   SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1
   ```
   or, if `mod_setenvif` is unavailable:
   ```apache
   <IfModule mod_rewrite.c>
   RewriteEngine On
   RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
   </IfModule>
   ```
4. If `pcip doctor --live` reports the connector **blocked** with an anti-bot
   message, allowlist the calling machine's IP in Site Tools → **Security**
   (SiteGround answers bots with an `sg-captcha` challenge that looks like a
   success to naive clients — PCIP refuses it rather than misreporting).
5. Verify:
   ```bash
   python -m pcip doctor --live
   python -m pcip route wordpress
   ```

### Optional — make publishing instant instead of ~60s

The site exposes a revalidation webhook that purges its cache immediately.
Set the same secret on both sides:

```
VERCEL_REVALIDATE_URL=https://passqual.com/api/revalidate
WP_REVALIDATE_SECRET=<a long random string>
```

and set `WP_REVALIDATE_SECRET` to the same value in the Vercel project's
environment, then redeploy. Without it, articles still go live — just within
the 60-second window. `pcip can wordpress.instant_revalidate` reports
`not_entitled` until both sides are set.

### While publishing is blocked

If step 3 is still pending, work does not have to stop:

```bash
python -m pcip prepare <output_id>
```

writes the finished, fully-reviewed article (body HTML, media with real alt
text, title, slug, excerpt, expected URL) into a folder with paste-by-hand
instructions. It enforces the same review and licensing gates as a real
publish, and needs no WordPress credentials at all.

Posts land as **drafts** unless you pass `--live` — deliberate, because on this
architecture "live" means live to patients within a minute.

---

## Phase 4 — Image generation providers (optional, add any subset)

The capability router uses whichever are configured. Priority order per the
architecture: **OpenAI default → Imagen photorealism → Ideogram typography →
Flux self-host**. Preview routing anytime:

```bash
python -m pcip media-plan healthcare_photo
python -m pcip media-plan social_quote
```

| Provider | Get a key | API docs | `.env` |
|---|---|---|---|
| **OpenAI Images** (default) | <https://platform.openai.com/api-keys> | <https://platform.openai.com/docs/guides/image-generation> | `OPENAI_API_KEY` |
| **Google Imagen** (photorealism) | <https://aistudio.google.com/apikey> | <https://ai.google.dev/gemini-api/docs/imagen> | `GOOGLE_AI_API_KEY` |
| **Ideogram** (typography) | <https://developer.ideogram.ai/> (Manage API → generate key) | <https://developer.ideogram.ai/api-reference/api-reference/generate-v3> | `IDEOGRAM_API_KEY` |
| **Flux / Black Forest Labs** (self-host/open) | <https://dashboard.bfl.ai/> | <https://docs.bfl.ai/> | `BFL_API_KEY` (+ `FLUX_ENDPOINT` if self-hosted) |

Exactly what to do for each: create an account → generate an API key on the
linked page → paste into `.env` → `python -m pcip status` to confirm.

---

## Phase 5 — Video generation providers (optional, add any subset)

Priority per the architecture: **Veo premium default → Runway production
fallback → Pika fast social → Luma stylized motion**.

| Provider | Get a key | API docs | `.env` |
|---|---|---|---|
| **Google Veo** (premium cinematic) | <https://aistudio.google.com/apikey> (same key as Imagen) | <https://ai.google.dev/gemini-api/docs/video> | `GOOGLE_AI_API_KEY` |
| **Runway** (production; image-to-video) | <https://dev.runwayml.com/> | <https://docs.dev.runwayml.com/> | `RUNWAY_API_KEY` |
| **Pika** (fast social clips) | via hosting partners, e.g. <https://fal.ai/models?q=pika> | partner model page | `PIKA_API_KEY` + `PIKA_ENDPOINT` |
| **Luma Dream Machine** (stylized motion) | <https://lumalabs.ai/dream-machine/api> | <https://docs.lumalabs.ai/> | `LUMA_API_KEY` |

Notes: Runway's generation API is image-to-video — PCIP passes a seed frame
(a Canva export or a generated image). Pika has no first-party public API;
set `PIKA_ENDPOINT` to your hosting partner's endpoint or skip it — the
router then sends quick reels to Runway/Veo automatically.

---

## Phase 6 — Social publishing (optional; hybrid: direct APIs + Buffer)

Direct tokens give full native capability and resilience; Buffer adds
scheduling/queues. Configure any subset — the decision engine routes
immediate posts direct-first and scheduled posts Buffer-first, with
automatic fallback. Preview anytime:

```bash
python -m pcip route facebook              # immediate → direct first
python -m pcip route facebook --scheduled  # scheduled → Buffer first
```

| Channel | Where to set up | Docs | `.env` |
|---|---|---|---|
| **Meta (FB Page + IG Business)** | <https://developers.facebook.com/> → create app → Graph API | IG publishing: <https://developers.facebook.com/docs/instagram-platform/content-publishing> | `META_PAGE_TOKEN`, `META_IG_USER_ID` |
| **Threads** | same Meta app → Threads use case | <https://developers.facebook.com/docs/threads> | `THREADS_TOKEN`, `THREADS_USER_ID` |
| **LinkedIn** | <https://developer.linkedin.com/> → create app → Community Management/Marketing | <https://learn.microsoft.com/en-us/linkedin/marketing/> | `LINKEDIN_TOKEN`, `LINKEDIN_ORG_URN` (e.g. `urn:li:organization:12345`) |
| **X** | <https://developer.x.com/> → project + app → OAuth2 user token with `tweet.write` | <https://docs.x.com/x-api/introduction> | `X_USER_TOKEN` |
| **YouTube** | <https://console.cloud.google.com/> → enable YouTube Data API v3 → OAuth consent + token | <https://developers.google.com/youtube/v3/docs/videos/insert> | `YOUTUBE_TOKEN` |
| **TikTok** | <https://developers.tiktok.com/> → app → Content Posting API (requires app review) | <https://developers.tiktok.com/doc/content-posting-api-get-started> | `TIKTOK_TOKEN` |
| **Buffer** (scheduler) | <https://buffer.com/developers/api> | same | `BUFFER_TOKEN` |

Realistic sequencing advice: Meta + LinkedIn are the highest-value and most
stable direct integrations — do those first. X is quick. TikTok requires an
app review cycle; YouTube requires an OAuth consent screen — schedule both
as background tasks, and let Buffer cover them in the meantime.

### Rehearse a post before you have any of those tokens

`--dry-run` runs the **real** adapter — the same code that would post — but
swaps the transport for a recorder. Nothing leaves the machine, no token is
needed, and the exact request is printed with credentials redacted:

```bash
python -m pcip publish <output_id> --channel instagram --dry-run
```

It reports which adapter the decision engine picked, the caption and its
length, every request that would have been sent, and exactly which
environment variables are still unset. Use it to check a caption against the
standard and to confirm a channel is wired before the first live post.

Two things a dry run deliberately does **not** do: it never records a
Publication in the graph (the graph is the history of what was published,
and a rehearsal is not), and it does not cover WordPress — that channel has
its own offline path, `python -m pcip prepare <output_id>`, which produces
the real article.

### What the standard requires of a social caption

Social posts are held to the part of the PassQual Health standard that
travels to a caption, not to the article rules (a 600-word, three-H2,
FAQ-bearing Instagram caption does not exist):

| Severity | Rule |
|---|---|
| blocker | no pediatric content — PassQual Health does not serve pediatrics |
| blocker | no outcome guarantees or superlatives |
| blocker | mental-health content must carry **988** and **911** |
| required | a route back to the practice: the phone number or passqual.com |
| required | within the platform's character limit (X 280, Threads 500, IG/TikTok 2200, LinkedIn 3000) |
| required | media on Instagram, TikTok and YouTube |
| advisory | `cerca de mí` phrasing in Spanish; at least one hashtag |

Passing `--text` means you wrote the caption and have taken it on, so the
required and advisory findings are waived. **The blockers are not waived** —
a caption reaches a patient exactly as directly as an article does.

---

## Phase 7 — First end-to-end run

```bash
# 1. Find a brand template and put its id in your brief's references
python -m pcip search --kind brand_template ""

# 2. Copy examples/brief.example.json → my-brief.json and edit it

# 3. Run (patient education shown — strictest pipeline)
python -m pcip run patient_education --brief my-brief.json
# → pauses at medical_review

# 4. Review the design in Canva, then approve each gate
python -m pcip approve <run_id> --gate medical_review --reviewer "Dr. Pascual"
# → pauses at brand_review; approve again → exports via official Canva API

# 5. Publish (WordPress = draft by default; social = decision-engine routed)
python -m pcip publish <output_id> --channel instagram --dry-run   # rehearse first
python -m pcip publish <output_id> --channel wordpress --title "..." --text "<p>...</p>"
python -m pcip publish <output_id> --channel instagram --text "caption #hashtags"
python -m pcip publish <output_id> --channel linkedin --schedule-at 2026-08-10T14:00:00Z --text "..."

# 6. Interrogate the graph
python -m pcip runs
python -m pcip graph <output_id>
```

---

## Security reminders

- `.env` is gitignored — never commit it. Rotate any token that ever
  appears in a terminal you've shared.
- All tokens are read from the environment only; PCIP never writes secrets
  to the graph database, logs, or exports.
- Patient-facing content: the `medical_review` gate cannot be auto-approved
  by configuration — that is intentional and enforced in code.
