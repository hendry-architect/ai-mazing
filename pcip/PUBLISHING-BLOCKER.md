# Publishing blocker: the Authorization header on wp.passqual.com

Status: **unresolved at the hosting layer.** PCIP works around it with
`pcip prepare`; automated publishing waits on the host.

## What is actually broken

WordPress authenticates an Application Password from `$_SERVER['PHP_AUTH_USER']`
and `$_SERVER['PHP_AUTH_PW']`. On this host neither is ever populated, so every
REST write returns `401 rest_not_logged_in` no matter how correct the
credentials are.

This was confirmed at the web-server layer, not inferred from WordPress's error
code: a header probe on the site reports the request as PHP receives it, and
shows `Authorization:` empty and `PHP_AUTH_USER: (not set)` for a request that
demonstrably carried a Basic credential.

## What has already been tried, and has not worked

All three documented `.htaccess` remedies are present in the live file
simultaneously:

```apache
SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1

<IfModule mod_rewrite.c>
RewriteEngine On
RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
</IfModule>

# BEGIN Authorization Header Fix
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteCond %{HTTP:Authorization} ^(.*)
RewriteRule .* - [E=HTTP_AUTHORIZATION:%1]
</IfModule>
# END Authorization Header Fix
```

The header still does not reach PHP. That is the signal to stop editing
`.htaccess`: these rules set an Apache environment variable, and something
above Apache — SiteGround's proxy layer, or the PHP-FPM parameter set — is
either dropping the header before Apache sees it or not forwarding the
variable to PHP. Neither is reachable from a file the account can edit.

Note also that even a working `E=HTTP_AUTHORIZATION` does not by itself
populate `PHP_AUTH_USER`/`PHP_AUTH_PW`, which is what WordPress reads. Under
CGI/FastCGI that decode has to happen somewhere, and on this stack it is not
happening.

## Site facts worth recording

- `passqual.com` and `wp.passqual.com` resolve differently (Vercel and
  SiteGround) but share **one** SiteGround document root; `wp.passqual.com` is
  a symlink. There is one `.htaccess` and one WordPress install.
- Wordfence is active as an `auto_prepend_file`, so it executes before every
  PHP request. Its path resolves inside the shared root and is correct.
- `auth_test.php` in the web root is a header diagnostic left from an earlier
  debugging session. It is publicly reachable and should be removed once this
  is resolved.
- `/wp-json/wp/v2/users` is publicly enumerable. Unrelated to this blocker,
  worth closing separately.

## Ticket text for SiteGround support

Send this once the control test confirms the probe is live and custom headers
do reach PHP. It gives support the finding rather than the symptom.

> On my account (passqual.com / wp.passqual.com, shared document root), the
> HTTP `Authorization` request header is not reaching PHP. This breaks the
> WordPress REST API with Application Passwords: every authenticated request
> returns `401 rest_not_logged_in` because `$_SERVER['PHP_AUTH_USER']` and
> `$_SERVER['PHP_AUTH_PW']` are never populated.
>
> What I have already verified:
>
> - A PHP probe in the web root shows `HTTP_AUTHORIZATION` empty and
>   `PHP_AUTH_USER` unset for a request that definitely sent a Basic
>   credential, and no `REDIRECT_HTTP_AUTHORIZATION` either.
> - All three documented `.htaccess` remedies are present simultaneously
>   (`SetEnvIf Authorization`, and two `RewriteRule ... [E=HTTP_AUTHORIZATION]`
>   variants). None has any effect, which is consistent with the header being
>   dropped before Apache processes the rules.
> - A control header (`X-Auth-Probe`) on the same request *does* reach PHP, so
>   custom headers are forwarded in general — `Authorization` specifically is
>   not.
>
> Please pass the `Authorization` header through to PHP for this account —
> typically by including `HTTP_AUTHORIZATION` in the PHP-FPM fastcgi
> parameters, or the equivalent in the proxy configuration. I do not need any
> file changed on my side; this is at a layer I cannot reach from Site Tools.

## The remaining options, in order of preference

1. **SiteGround support.** They can inspect and change the proxy and PHP-FPM
   configuration, which the account cannot. This is a known platform quirk and
   a routine ticket. Preferred because it fixes the cause and adds nothing to
   the site.
2. **Jetpack / WordPress.com API.** `public-api.wordpress.com` proxies to a
   connected site, so requests never traverse this host's web server and the
   stripped header becomes irrelevant. Requires connecting Jetpack (checked:
   not currently connected). PCIP supports this today via
   `WORDPRESS_COM_TOKEN`.
3. **A must-use plugin that restores the header** — `examples/wordpress/`.
   Last resort. It works, but it adds pre-authentication code to a location
   designed to resist removal, which is a real cost and was rightly
   challenged in review. Its credential-mirror fallback is off unless
   `wp-config.php` defines `PCIP_ALLOW_MIRROR_HEADER`.

## What is not blocked

`pcip prepare` produces the complete article — body, media, alt text, slug,
excerpt, and the exact public URL — with no credentials and no server changes.
Publishing by hand takes a few minutes and exercises the whole pipeline. The
automation is an optimisation on a pipeline that already works end to end.
