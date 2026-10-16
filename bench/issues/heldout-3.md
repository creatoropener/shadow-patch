Anyone who knows a subscription ID can invoke cancellation without app authentication or ownership checks.

Authenticate the customer or issue a short-lived signed retention-session token through an authenticated merchant integration. Bind the session to the server's customer/subscription mapping. Enforce ownership on every subscription read and mutation. Treat URL parameters and localStorage as navigation inputs, never ownership proof. Test that a second customer receives 403 and causes no provider call.
