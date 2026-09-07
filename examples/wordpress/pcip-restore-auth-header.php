<?php
/**
 * Plugin Name: PCIP — Restore Authorization Header
 * Description: Lets the WordPress REST API authenticate on hosts that strip the
 *              Authorization header before PHP sees it (SiteGround and other
 *              CGI/FastCGI stacks), which otherwise makes every Application
 *              Password fail with 401 rest_not_logged_in.
 * Version:     1.0.0
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

    // 3. Last resort: the mirror header PCIP sends, which is not stripped.
    //    Only honoured over HTTPS, so credentials are never read in clear text.
    if ( empty( $_SERVER['HTTP_AUTHORIZATION'] ) && ! empty( $_SERVER['HTTP_X_PCIP_AUTHORIZATION'] ) ) {
        $is_https = ( ! empty( $_SERVER['HTTPS'] ) && 'off' !== $_SERVER['HTTPS'] )
            || ( ! empty( $_SERVER['HTTP_X_FORWARDED_PROTO'] ) && 'https' === $_SERVER['HTTP_X_FORWARDED_PROTO'] );
        if ( $is_https ) {
            $_SERVER['HTTP_AUTHORIZATION'] = $_SERVER['HTTP_X_PCIP_AUTHORIZATION'];
        }
    }
}
