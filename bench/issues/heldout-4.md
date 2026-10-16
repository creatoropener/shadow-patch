The frontend appended the green success message “Subscription cancelled.” post() resolves on HTTP errors because it only calls r.json(), and the cancel handler discards that JSON.

Make the shared request helper reject non-success HTTP responses. Require a successful response with ok: true before reporting cancellation. Catch network errors, provide a retry, and refresh canonical subscription state without presenting failure as success. Disable duplicate clicks while the operation is unresolved.
