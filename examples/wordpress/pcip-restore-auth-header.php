<?php
/**
 * Plugin Name: PCIP — Restore Authorization Header
 * Description: Lets the WordPress REST API authenticate on hosts that strip the
 *              Authorization header before PHP sees it (SiteGround and other
 *              CGI/FastCGI stacks), which otherwise makes every Application
 *              Password fail with 401 rest_not_logged_in.
 * Version:     1.0.0
 *
 * TRY THE .htaccess FIX FIRST. This plugin should not be your first move.
 * Add to the .htaccess in the WordPress root and re-test:
 *
 *     SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1
 *
 * That is configuration, not code, and it is trivially reversible. Install
 * this file only if that rule proves insufficient on your stack.
 *
 * WHAT THIS DOES AND DOES NOT DO: it repopulates $_SERVER['HTTP_AUTHORIZATION']
 * from places the real header may still be readable. It does not authenticate
 * anyone, create or elevate a user, set a cookie, bypass a permission check,
 * write to the database, or make a network request — read it, it is 60 lines
 * with no branches beyond the three lookups. Whatever it recovers is handed to
 * WordPress's normal authentication, which still rejects an invalid password.
 * Without it, WordPress receives no credentials at all and answers every
 * request with rest_not_logged_in, which is the symptom this addresses.
 *
 * INSTALL: upload to  wp-content/mu-plugins/pcip-restore-auth-header.php
 *          (create the mu-plugins folder if it does not exist — files there
 *           load automatically and cannot be deactivated by accident).
 *
 * This runs at file-load time, before WordPress resolves the current user,
 * which is why it is a must-use plugin rather than a normal one.
 */

if ( empty( $_SERVER['HTTP_AUTHORIZATION'] ) ) {

    // 1. Apache commonly forwards it under a REDIRECT_ prefix after a rewrite.
    foreach ( array(
        'REDIRECT_HTTP_AUTHORIZATION',
        'REDIRECT_REDIRECT_HTTP_AUTHORIZATION',
    ) as $candidate ) {
        if ( ! empty( $_SERVER[ $candidate ] ) ) {
            $_SERVER['HTTP_AUTHORIZATION'] = $_SERVER[ $candidate ];
            break;
        }
    }

    // 2. mod_php can still see the real header even when $_SERVER cannot.
    if ( empty( $_SERVER['HTTP_AUTHORIZATION'] ) && function_exists( 'apache_request_headers' ) ) {
        foreach ( (array) apache_request_headers() as $name => $value ) {
            if ( 'authorization' === strtolower( $name ) && ! empty( $value ) ) {
                $_SERVER['HTTP_AUTHORIZATION'] = $value;
                break;
            }
        }
    }

    // 3. Last resort, and OFF unless you deliberately switch it on: accept a
    //    mirrored credential from a non-standard header.
    //
    //    Read this one critically, because it is the only part of this file
    //    that treats something other than the standard header as a credential
    //    source. It does not grant access — whatever it copies is still
    //    validated by WordPress exactly as normal, so an invalid password
    //    still fails — but it does re-open a REST authentication path that a
    //    header-stripping host was incidentally closing. That is a real, if
    //    modest, change to your exposure, and it should be a decision rather
    //    than a default.
    //
    //    To enable, add this line to wp-config.php:
    //        define( 'PCIP_ALLOW_MIRROR_HEADER', true );
    //    Steps 1 and 2 above are the standard WordPress fix and need nothing.
    if ( empty( $_SERVER['HTTP_AUTHORIZATION'] )
        && defined( 'PCIP_ALLOW_MIRROR_HEADER' ) && PCIP_ALLOW_MIRROR_HEADER
        && ! empty( $_SERVER['HTTP_X_PCIP_AUTHORIZATION'] ) ) {

        // HTTPS only, so a mirrored credential is never accepted in clear text.
        $is_https = ( ! empty( $_SERVER['HTTPS'] ) && 'off' !== $_SERVER['HTTPS'] )
            || ( ! empty( $_SERVER['HTTP_X_FORWARDED_PROTO'] ) && 'https' === $_SERVER['HTTP_X_FORWARDED_PROTO'] );
        if ( $is_https ) {
            $_SERVER['HTTP_AUTHORIZATION'] = $_SERVER['HTTP_X_PCIP_AUTHORIZATION'];
        }
    }
}
