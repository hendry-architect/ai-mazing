# Publishing to wp.passqual.com — RESOLVED

Status: **working.** PCIP publishes over the WordPress REST API with an
Application Password. No server change was needed, no plugin was installed, and
the support ticket drafted here should not be sent.

Kept because the wrong diagnosis was expensive and the reasoning error is worth
not repeating.

## What actually happened

The first authenticated publish succeeded on the REST transport, uploading
media and creating the post. That is only possible if WordPress received and
validated the Application Password from the `Authorization` header — so the
header was reaching PHP the entire time.

## Why it looked like the header was stripped

Two mistakes compounded.

**`rest_not_logged_in` was read as proof of a missing credential.** Every probe
used a username that does not exist on the site (`probe`, `pcip-test`).
WordPress does not report "wrong password" for an unknown user: application
password authentication declines, the request continues unauthenticated, and an
endpoint requiring auth answers `rest_not_logged_in` — the same code a genuinely
absent credential produces. The test could not distinguish the two, and the
conclusion was drawn as if it could.

**The header probe was reading a cached response.** `auth_test.php` reported
`Authorization:` empty even for requests that carried one, and the audit's own
output showed `x-proxy-cache: HIT` on that response. A unique query string was
added to defeat caching and the HIT persisted, which should have invalidated
the probe rather than being noted in passing. Its later results were not
evidence about what PHP received.

The `.htaccess` rules stacked in the file, and the empty `HTTP_AUTHORIZATION`
variable, were consistent with the wrong story and did nothing to contradict
it — an empty variable set unconditionally by a rewrite rule looks identical
whether or not the header arrived.

## The lesson

A diagnostic that cannot distinguish two causes must not be reported as
choosing between them. The correct test for "does WordPress receive the
credential" was always to use a **real** account and see whether an
authenticated request succeeds — which is what publishing did, in one attempt,
after several rounds of inference from a code that never carried that meaning.

## Site facts worth keeping

- `passqual.com` and `wp.passqual.com` resolve to different services (Vercel and
  SiteGround) but share one SiteGround document root; `wp.passqual.com` is a
  symlink. There is one `.htaccess` and one WordPress install.
- `WORDPRESS_URL` must be `https://wp.passqual.com` — the REST origin.
  `WORDPRESS_PUBLIC_SITE` is `https://passqual.com`, where readers land. The
  public site rewrites `/wp-json/*` to a blocked route, so pointing the origin
  at it produces a 404 with an empty body.
- A shell variable exported non-empty overrides `.env`. This cost several
  rounds; `pcip publish` now prints the resolved origin and any shadowing.
- Wordfence runs as an `auto_prepend_file`. It is not blocking REST writes: an
  unauthenticated `POST /wp-json/wp/v2/media` returns 401, which is WordPress
  refusing an anonymous write.
- XML-RPC is enabled and exposes `wp.newPost`. PCIP keeps it as an automatic
  fallback for a genuine header-stripping host; it was not needed here.

## Cleanup

- `auth_test.php` in the web root should be deleted. It is publicly reachable
  and echoes the raw `Authorization` value.
- `/wp-json/wp/v2/users` is publicly enumerable — worth closing, unrelated to
  publishing.
- The stacked `.htaccess` Authorization rules are harmless but redundant now
  that the header is known to arrive; they can be reduced to one, or removed
  and re-tested.
