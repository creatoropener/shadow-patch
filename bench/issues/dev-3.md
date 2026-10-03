When an external target responded with an HTTP 301, 302, 307, or 308 redirect, fetchWithRedirects recursively called execute(nextUrl, redirectCount + 1) without re-verifying the redirect destination.

Ensure every redirect iteration re-invokes validateUrlForSsrf(nextUrl) prior to executing the subsequent HTTP request.
