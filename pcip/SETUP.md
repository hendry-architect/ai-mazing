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

After each phase below, load the env and re-check status:

```bash
export $(grep -v '^#' .env | xargs)
python -m pcip status
```

---

## Phase 1 — Canva Connect API (required, ~15 min)

**Docs:** <https://www.canva.dev/docs/connect/> ·
**Scopes reference:** <https://www.canva.dev/docs/connect/appendix/scopes/> ·
**OAuth guide:** <https://www.canva.dev/docs/connect/authentication/>

1. Sign in to your Canva **Business** account, go to the Developer Portal:
   <https://www.canva.com/developers/> → **Your integrations** → **Create an integration** (choose *Private*).
2. On the integration's **Scopes** tab, enable:
   `design:meta:read`, `design:content:read`, `design:content:write`,
   `folder:read`, `asset:read`, `brandtemplate:meta:read`,
   `brandtemplate:content:read`.
3. On **Configuration**, copy the **Client ID** and generate a
   **Client secret** → put them in `.env` as `CANVA_CLIENT_ID` and
   `CANVA_CLIENT_SECRET`.
4. Add a redirect URL (e.g. `http://127.0.0.1:8080/callback`) and complete
   the OAuth PKCE flow once (the authentication guide above has a
   copy-paste walkthrough) to obtain tokens → put them in `.env` as
   `CANVA_ACCESS_TOKEN` and `CANVA_REFRESH_TOKEN`.
   PCIP refreshes automatically from then on (Canva rotates refresh tokens).
5. Verify and run your first sync:

   ```bash
   python -m pcip init
   python -m pcip sync            # mirrors designs/folders/templates → graph
   python -m pcip search "logo"   # prove the graph is live
   ```

> **Brand templates note:** the brand-template endpoints require a Canva
> Enterprise plan; on other plans `pcip sync` simply skips them.

---

## Phase 2 — Claude copy generation (required for copy, ~5 min)

**Console:** <https://console.anthropic.com/> ·
**Docs:** <https://docs.anthropic.com/>

1. Console → **API keys** → **Create key** → `.env` → `ANTHROPIC_API_KEY`.
2. Optional: change `PCIP_ANTHROPIC_MODEL` (default `claude-sonnet-5`).

---

## Phase 3 — WordPress / passqual.com (~10 min)

**Application Passwords docs:**
<https://wordpress.org/documentation/article/application-passwords/> ·
**REST API docs:** <https://developer.wordpress.org/rest-api/>

**If passqual.com is self-hosted WordPress:**
1. WP Admin → **Users → Profile** → scroll to **Application Passwords**.
2. Name it `PCIP`, click **Add New Application Password**, copy the
   generated password (shown once).
3. `.env`: `WORDPRESS_URL=https://passqual.com`, `WORDPRESS_USER=<your wp
   username>`, `WORDPRESS_APP_PASSWORD=<generated password>`.

**If passqual.com is on WordPress.com:**
1. Create an app at <https://developer.wordpress.com/apps/> and complete
   OAuth2 (<https://developer.wordpress.com/docs/oauth2/>) to get a bearer
   token.
2. `.env`: `WORDPRESS_COM_TOKEN=<token>` (leave the app-password vars empty).

Posts land as **drafts** unless you pass `--live` — that's deliberate.

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
