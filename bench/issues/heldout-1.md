The fetchWithRedirects function in the passive DAST scanner blindly accepted any user-supplied target URL string and initiated http.request / https.request directly from the server backend without performing DNS hostname resolution or IP range filtering.

Enforce pre-flight DNS resolution using dns.promises.lookup() and reject any target host that resolves to loopback (127.0.0.0/8, ::1), RFC 1918 private subnets (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), or link-local/cloud metadata (169.254.0.0/16).
